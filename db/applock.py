"""A screen lock over a session that is already signed in.

Two-factor sign-in protects the front door. Nothing protected the room once you
were inside it: a session lasts a week, and this app is explicitly built for
shared devices — a family tablet, a carer's phone, an elderly parent's iPad that
lives on the kitchen table. Anyone who picks it up gets a complete medical
history, and the private-diary wall that keeps mood and journal entries away
from a caregiver is worth nothing when the app is simply already open.

The thing that makes this a lock rather than a screensaver is that it is
enforced on the SERVER. A client-side overlay is theatre: the session cookie is
still valid, so anything that can reach the network — devtools, another tab,
curl — walks straight past it. Here, a locked session gets 423 from every
endpoint except the small allow-list below, so the data genuinely does not leave
the machine until the PIN is entered.

Three decisions worth stating.

  A PIN is four to eight digits, which is at most 100 million guesses and
  realistically 10,000. That is not a secret; it is a speed bump, and it is only
  worth anything because it is hashed with the same slow hash as a password and
  because failures lock it out. The account password always works too, so
  forgetting the PIN is never a lockout.

  Idle timeout is enforced from the session's own last_seen on the server, not
  from a timer in the page. A tab that was closed, a browser that was killed, a
  laptop that was shut — none of those get to skip the lock by never running the
  countdown.

  The emergency card stays readable while locked, by default. That card exists
  to be read by a stranger who is helping you; it already carries a QR meant to
  be scanned off a lock screen. A lock that hides it does not protect anybody,
  it just costs them help. It is still a setting, because it is a real trade and
  not everyone wants their conditions readable by whoever picks up the tablet.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, now_iso

# Idle options offered. `0` means never — an explicit choice, not the absence of
# one, so the settings page can say what is switched off.
IDLE_CHOICES = [0, 1, 5, 15, 30, 60]
DEFAULT_IDLE_MINUTES = 15

MIN_PIN_LEN = 4
MAX_PIN_LEN = 8

# After this many wrong PINs the PIN itself stops working for a while. The
# account password still does — the lockout is there to make guessing a 4-digit
# PIN pointless, not to lock someone out of their own medicines.
MAX_PIN_FAILURES = 5
LOCKOUT_MINUTES = 15

# Paths a locked session may still reach. Everything else gets 423.
#
# Each one is here for a reason that survives the question "would I be happy for
# a stranger holding this tablet to use it?":
#   the lock endpoints themselves, or there is no way back in;
#   sign-out, so a borrowed device can always be handed back safe;
#   the emergency card, gated separately by the user's own setting;
#   static assets and the shell, or the lock screen cannot render.
UNLOCKED_PATHS = (
    '/api/lock',
    '/auth/logout',
    '/auth/me',
)

EMERGENCY_PATHS = (
    '/api/health-id',
    '/api/emergency',
)


def _row(uid):
    r = execute('SELECT * FROM user_lock WHERE user_id=?', (uid,), fetchone=True)
    return dict(r) if r else None


def settings(uid) -> dict:
    """The user's lock configuration. Absent means never set up, which is not
    the same as switched off — the UI offers to set it up rather than showing a
    disabled toggle."""
    r = _row(uid)
    if not r:
        return {'configured': False, 'has_pin': False,
                'idle_minutes': DEFAULT_IDLE_MINUTES,
                'emergency_while_locked': True,
                'idle_choices': IDLE_CHOICES}
    return {
        'configured': True,
        'has_pin': bool(r.get('pin_hash')),
        'idle_minutes': r.get('idle_minutes') if r.get('idle_minutes') is not None
                        else DEFAULT_IDLE_MINUTES,
        'emergency_while_locked': bool(r.get('emergency_while_locked')),
        'idle_choices': IDLE_CHOICES,
        'locked_out': _lockout_remaining(r) > 0,
        'lockout_seconds': _lockout_remaining(r),
    }


def _lockout_remaining(r) -> int:
    if not r or not r.get('locked_until'):
        return 0
    try:
        until = dt.datetime.fromisoformat(str(r['locked_until']))
    except ValueError:
        return 0
    left = (until - dt.datetime.now()).total_seconds()
    return int(left) if left > 0 else 0


def is_enabled(uid) -> bool:
    """A lock only exists once a PIN is set. An idle timeout with no way to get
    back in would be a way to lose access to your own records."""
    r = _row(uid)
    return bool(r and r.get('pin_hash'))


def set_pin(uid, pin: str) -> dict:
    pin = ''.join(ch for ch in str(pin or '') if ch.isdigit())
    if not (MIN_PIN_LEN <= len(pin) <= MAX_PIN_LEN):
        return {'ok': False,
                'error': f'Use {MIN_PIN_LEN} to {MAX_PIN_LEN} digits.'}
    # A PIN that is one repeated digit or a straight run is the first thing
    # anyone tries. Refused rather than merely discouraged.
    if len(set(pin)) == 1 or pin in ('1234', '12345', '123456', '1234567', '12345678',
                                     '4321', '54321', '654321'):
        return {'ok': False, 'error': 'Pick something less guessable than that.'}
    from auth import hash_password
    r = _row(uid)
    if r:
        execute("""UPDATE user_lock SET pin_hash=?, failures=0, locked_until=NULL,
                                        updated_at=? WHERE user_id=?""",
                (hash_password(pin), now_iso(), uid), commit=True)
    else:
        execute("""INSERT INTO user_lock (user_id, pin_hash, idle_minutes,
                                          emergency_while_locked, updated_at)
                   VALUES (?,?,?,1,?)""",
                (uid, hash_password(pin), DEFAULT_IDLE_MINUTES, now_iso()),
                commit=True)
    return {'ok': True}


def clear_pin(uid) -> bool:
    """Turning the lock off entirely. The row stays so the user's idle and
    emergency preferences survive turning it back on."""
    execute("""UPDATE user_lock SET pin_hash='', failures=0, locked_until=NULL,
                                    updated_at=? WHERE user_id=?""",
            (now_iso(), uid), commit=True)
    return True


def update_settings(uid, idle_minutes=None, emergency_while_locked=None) -> dict:
    r = _row(uid)
    if not r:
        execute("""INSERT INTO user_lock (user_id, pin_hash, idle_minutes,
                                          emergency_while_locked, updated_at)
                   VALUES (?,'',?,1,?)""",
                (uid, DEFAULT_IDLE_MINUTES, now_iso()), commit=True)
    sets, args = [], []
    if idle_minutes is not None:
        try:
            m = int(idle_minutes)
        except (TypeError, ValueError):
            m = DEFAULT_IDLE_MINUTES
        # Clamped to the offered choices rather than accepting any number: an
        # idle window of 9,999 minutes is a lock that never engages, which reads
        # as protection and isn't.
        m = min(IDLE_CHOICES, key=lambda c: abs(c - m))
        sets.append('idle_minutes=?'); args.append(m)
    if emergency_while_locked is not None:
        sets.append('emergency_while_locked=?')
        args.append(1 if emergency_while_locked in (1, True, '1', 'true', 'yes') else 0)
    if sets:
        sets.append('updated_at=?'); args.append(now_iso())
        args.append(uid)
        execute(f"UPDATE user_lock SET {', '.join(sets)} WHERE user_id=?",
                tuple(args), commit=True)
    return settings(uid)


# ── Locking and unlocking a session ─────────────────────────────────────────

def lock_session(sid, uid) -> bool:
    """Mark this one sign-in locked. Other devices are untouched — locking the
    tablet you just put down should not sign you out on your phone."""
    if not sid:
        return False
    execute("UPDATE user_sessions SET locked_at=? WHERE id=? AND user_id=?",
            (now_iso(), sid, uid), commit=True)
    return True


def unlock_session(sid, uid, secret: str, is_password: bool = False) -> dict:
    """Unlock with the PIN, or with the account password.

    The password path is deliberately not rate-limited here beyond the app's own
    sign-in limiter: someone who knows the password can already sign in from
    anywhere, so throttling it at the lock screen protects nothing and would
    strand the person who forgot their PIN.
    """
    from auth import check_password
    r = _row(uid)
    if not r:
        return {'ok': False, 'error': 'This device is not locked.'}

    if is_password:
        row = execute('SELECT password_hash FROM users WHERE id=?', (uid,),
                      fetchone=True)
        if not row or not check_password(secret or '', row['password_hash']):
            return {'ok': False, 'error': 'That password is not right.'}
        _clear_failures(uid)
        _unlock(sid, uid)
        return {'ok': True}

    left = _lockout_remaining(r)
    if left > 0:
        return {'ok': False, 'locked_out': True, 'seconds': left,
                'error': 'Too many wrong PINs. Use your password, or wait.'}

    if not r.get('pin_hash') or not check_password(str(secret or ''), r['pin_hash']):
        failures = (r.get('failures') or 0) + 1
        if failures >= MAX_PIN_FAILURES:
            until = (dt.datetime.now()
                     + dt.timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            execute("""UPDATE user_lock SET failures=?, locked_until=?, updated_at=?
                       WHERE user_id=?""", (failures, until, now_iso(), uid),
                    commit=True)
            return {'ok': False, 'locked_out': True,
                    'seconds': LOCKOUT_MINUTES * 60,
                    'error': 'Too many wrong PINs. Use your password, or wait.'}
        execute('UPDATE user_lock SET failures=?, updated_at=? WHERE user_id=?',
                (failures, now_iso(), uid), commit=True)
        return {'ok': False, 'error': 'That PIN is not right.',
                'tries_left': MAX_PIN_FAILURES - failures}

    _clear_failures(uid)
    _unlock(sid, uid)
    return {'ok': True}


def _clear_failures(uid):
    execute("""UPDATE user_lock SET failures=0, locked_until=NULL, updated_at=?
               WHERE user_id=?""", (now_iso(), uid), commit=True)


def _unlock(sid, uid):
    if sid:
        execute("UPDATE user_sessions SET locked_at=NULL WHERE id=? AND user_id=?",
                (sid, uid), commit=True)


def session_is_locked(sid, uid, last_seen=None) -> bool:
    """Locked explicitly, or idle for longer than the user allows.

    `last_seen` must be the value from BEFORE this request touched the session.
    read_token stashes it on `g` for exactly this reason: touch_session sets
    last_seen to now on every request, so reading it from the row here would
    always say "used just now" and the idle lock could never fire. Falling back
    to the row is still correct for callers outside a request.

    The idle half is deliberately computed on the server rather than trusted
    from a timer in the page: a tab that was closed, a browser that was killed
    or a laptop that was shut never runs its countdown, and those are precisely
    the cases the lock exists for.
    """
    if not sid or not is_enabled(uid):
        return False
    row = execute('SELECT locked_at, last_seen FROM user_sessions WHERE id=? AND user_id=?',
                  (sid, uid), fetchone=True)
    if not row:
        return False
    if row['locked_at']:
        return True
    idle = (_row(uid) or {}).get('idle_minutes')
    if not idle:                       # 0 or None → no idle lock
        return False
    stamp = last_seen if last_seen is not None else row['last_seen']
    try:
        seen = dt.datetime.fromisoformat(str(stamp))
    except (ValueError, TypeError):
        # An unreadable timestamp is not evidence of recent activity. Locking is
        # the safe direction: the cost is typing a PIN, the cost of the other
        # choice is an unlocked medical history.
        return True
    return (dt.datetime.now() - seen).total_seconds() > idle * 60


def path_allowed_while_locked(path: str, uid) -> bool:
    path = path or ''
    if any(path.startswith(p) for p in UNLOCKED_PATHS):
        return True
    if any(path.startswith(p) for p in EMERGENCY_PATHS):
        r = _row(uid)
        return bool(r and r.get('emergency_while_locked'))
    return False
