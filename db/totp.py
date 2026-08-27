"""Second-factor sign-in, built from the standard library.

A complete medical history sat behind one password. TOTP (RFC 6238) is the
ordinary answer and is small enough to implement directly — about thirty lines
of HMAC — which is better here than a dependency: this is the code path that
decides whether someone can reach their own medicines, and it should be
readable in one sitting.

No cryptography is invented. RFC 4226 (HOTP) is HMAC-SHA1 over a counter with
the published dynamic-truncation step; RFC 6238 makes the counter a 30-second
time step. Both are followed exactly, and the tests check the vectors published
in the RFCs rather than checking the code against itself.

Four decisions that matter more than the maths:

  Enabling requires PROOF. The secret is stored the moment it is generated, but
  two-factor is not enforced until a correct code has been entered. Turning it on
  and discovering afterwards that the clock is wrong is how people lock
  themselves out of their own records.

  A used code cannot be reused. The step it was accepted at is recorded, so
  someone reading a code over a shoulder — or off a shared screen — cannot
  replay it inside its own 30-second window.

  Recovery codes are hashed, shown once, and single-use. They are passwords by
  another name; storing them in the clear would undo the point of the feature.

  Losing the phone is a foreseeable event, not an edge case. The recovery codes
  exist for exactly that, the UI says so before enabling, and there is a
  documented way back that does not involve losing the account.
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time

from .core import execute, now_iso

DIGITS = 6
STEP_SECONDS = 30
# One step either side. Enough for a phone clock that drifts a few seconds;
# not so wide that a shoulder-surfed code stays useful for minutes.
DRIFT_STEPS = 1

RECOVERY_CODE_COUNT = 10
ISSUER = 'Arogo'


# ── RFC 4226 / 6238 ─────────────────────────────────────────────────────────

def _hotp(secret_bytes: bytes, counter: int) -> str:
    """HOTP as published: HMAC-SHA1 over the 8-byte counter, then dynamic
    truncation using the low nibble of the last byte as an offset."""
    mac = hmac.new(secret_bytes, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack('>I', mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def _b32decode(secret: str) -> bytes:
    # Authenticator apps show the secret without padding; add it back before
    # decoding rather than requiring the user to type it perfectly.
    s = str(secret or '').strip().replace(' ', '').upper()
    return base64.b32decode(s + '=' * (-len(s) % 8))


def current_step(at: float = None) -> int:
    return int((at if at is not None else time.time()) // STEP_SECONDS)


def code_at(secret: str, step: int) -> str:
    return _hotp(_b32decode(secret), step)


def generate_secret() -> str:
    """160 bits, the RFC 4226 recommendation, base32 for the authenticator app."""
    return base64.b32encode(os.urandom(20)).decode('ascii').rstrip('=')


def provisioning_uri(secret: str, account: str) -> str:
    """The otpauth:// URI an authenticator scans."""
    from urllib.parse import quote
    label = quote(f'{ISSUER}:{account}', safe='')
    return (f'otpauth://totp/{label}?secret={secret}'
            f'&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP_SECONDS}')


# ── Recovery codes ──────────────────────────────────────────────────────────

def _hash_code(code: str) -> str:
    return hashlib.sha256(_normalise(code).encode()).hexdigest()


def _normalise(code: str) -> str:
    return ''.join(ch for ch in str(code or '').lower() if ch.isalnum())


def generate_recovery_codes(n: int = RECOVERY_CODE_COUNT) -> list:
    """Readable, unambiguous codes. Shown once and never again."""
    alphabet = '23456789abcdefghjkmnpqrstuvwxyz'      # no 0/o/1/l/i
    out = []
    for _ in range(n):
        raw = ''.join(secrets.choice(alphabet) for _ in range(10))
        out.append(f'{raw[:5]}-{raw[5:]}')
    return out


# ── Enrolment ───────────────────────────────────────────────────────────────

def get_row(uid):
    r = execute('SELECT * FROM user_totp WHERE user_id=?', (uid,), fetchone=True)
    return dict(r) if r else None


def is_enabled(uid) -> bool:
    """Only a CONFIRMED enrolment counts. An unconfirmed secret must never gate
    a sign-in, or a half-finished setup locks the account."""
    r = get_row(uid)
    return bool(r and r.get('confirmed_at'))


def begin_enrolment(uid, account_email: str) -> dict:
    """Create (or replace) an unconfirmed secret and return what the user needs
    to scan. Replacing is deliberate: an abandoned half-setup should not block a
    fresh attempt."""
    secret = generate_secret()
    execute('DELETE FROM user_totp WHERE user_id=?', (uid,), commit=True)
    execute("""INSERT INTO user_totp (user_id, secret, recovery, created_at)
               VALUES (?,?,?,?)""",
            (uid, secret, '', now_iso()), commit=True)
    return {'secret': secret,
            'uri': provisioning_uri(secret, account_email),
            'digits': DIGITS, 'period': STEP_SECONDS}


def confirm_enrolment(uid, code: str) -> dict:
    """Turn it on only after a real code proves the authenticator works."""
    r = get_row(uid)
    if not r:
        return {'ok': False, 'error': 'Start setup again.'}
    if r.get('confirmed_at'):
        return {'ok': False, 'error': 'Two-factor sign-in is already on.'}
    if not _verify_code(r['secret'], code, r.get('last_used_step')):
        return {'ok': False, 'error': "That code didn't match. Check your "
                                      "authenticator app's time is correct."}
    codes = generate_recovery_codes()
    execute("""UPDATE user_totp SET confirmed_at=?, recovery=?, last_used_step=?
               WHERE user_id=?""",
            (now_iso(), ','.join(_hash_code(c) for c in codes),
             current_step(), uid), commit=True)
    # Returned exactly once. Nothing stores them in a readable form after this.
    return {'ok': True, 'recovery_codes': codes}


def disable(uid) -> bool:
    execute('DELETE FROM user_totp WHERE user_id=?', (uid,), commit=True)
    return True


def regenerate_recovery_codes(uid) -> list:
    """A fresh set, replacing every old one.

    Needed because the codes are shown exactly once: someone who closes that
    screen too early, or uses their last code, otherwise has 2FA on and no way
    back in if the phone dies. Returns [] when 2FA isn't actually on — issuing
    recovery codes for an enrolment that was never confirmed would hand out
    credentials to an account that doesn't use them.
    """
    if not is_enabled(uid):
        return []
    codes = generate_recovery_codes()
    execute('UPDATE user_totp SET recovery=? WHERE user_id=?',
            (','.join(_hash_code(c) for c in codes), uid), commit=True)
    return codes


# ── Verification ────────────────────────────────────────────────────────────

def _verify_code(secret, code, last_used_step) -> bool:
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != DIGITS:
        return False
    now = current_step()
    for delta in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
        step = now + delta
        # A code already accepted cannot be accepted again, even inside its own
        # window — otherwise a code read over a shoulder stays usable.
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return False


def verify(uid, code: str) -> bool:
    """Check a code (or a recovery code) and burn it."""
    r = get_row(uid)
    if not r or not r.get('confirmed_at'):
        return False
    step = _verify_code(r['secret'], code, r.get('last_used_step'))
    if step:
        execute('UPDATE user_totp SET last_used_step=? WHERE user_id=?',
                (step, uid), commit=True)
        return True
    return _consume_recovery(uid, r, code)


def _consume_recovery(uid, row, code) -> bool:
    """Single-use by construction: the hash is removed on success."""
    stored = [h for h in (row.get('recovery') or '').split(',') if h]
    if not stored:
        return False
    want = _hash_code(code)
    for h in stored:
        if hmac.compare_digest(h, want):
            stored.remove(h)
            execute('UPDATE user_totp SET recovery=? WHERE user_id=?',
                    (','.join(stored), uid), commit=True)
            return True
    return False


def recovery_codes_left(uid) -> int:
    r = get_row(uid)
    if not r:
        return 0
    return len([h for h in (r.get('recovery') or '').split(',') if h])
