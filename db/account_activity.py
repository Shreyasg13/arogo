"""Who can see this account, and what changed about that.

Three things the app could not answer:

Where am I signed in? Tokens are stateless — signed, carrying a user id and a
version — so the only lever was token_version, which signs out every device at
once. Losing a phone meant logging every other device out too, which is enough
friction that people put it off.

Did anything change? A password change, a caregiver being given access, an
export being downloaded: all happened silently. Someone who suspects their
account has been touched had nowhere to look.

Has that share link been opened? A snapshot could be sent to a doctor with no
way to tell whether it arrived, or whether it was opened by more people than
expected.

Two rules this module keeps to.

It records less than it could. No IP addresses, no raw user agents. `device` is
"Chrome on Windows" — enough to recognise your own phone in a list, not enough
to be a location history. A security feature that quietly grows a tracking log
has taken more than it gave.

The log is append-only. A security log the account holder can edit is not a
security log, so there is no delete and no edit — only the account itself going
away takes it.
"""
import datetime as dt

from .core import execute, current_user_id, new_id, now_iso

# Sessions idle longer than this are hidden from the list. They are already
# useless — the token itself expires — and showing months of dead rows buries
# the one device the user is actually looking for.
STALE_SESSION_DAYS = 60

# What the log can record. A fixed vocabulary so the page can describe each one
# in plain words rather than printing a raw string at the user.
EVENT_KINDS = {
    'signed_in': 'Signed in',
    'signed_out_device': 'Signed out a device',
    'signed_out_all': 'Signed out everywhere',
    'password_changed': 'Password changed',
    'two_factor_enabled': 'Turned on two-factor sign-in',
    'two_factor_disabled': 'Turned off two-factor sign-in',
    'two_factor_recovery_codes_regenerated': 'Made new recovery codes',
    'caregiver_granted': 'Gave someone access',
    'caregiver_revoked': 'Removed someone\'s access',
    'manage_granted': 'Allowed someone to manage this account',
    'manage_revoked': 'Stopped someone managing this account',
    'export_downloaded': 'Downloaded your data',
    'backup_downloaded': 'Downloaded a backup',
    'data_restored': 'Restored from a backup',
    'share_created': 'Created a share link',
    'share_revoked': 'Revoked a share link',
    'account_deleted': 'Account deletion requested',
}


def describe_device(user_agent: str) -> str:
    """A coarse, recognisable name for a browser. Never the raw string.

    Kept crude on purpose: the goal is "is that my phone or not", and a longer
    fingerprint would be more identifying without being more useful.
    """
    ua = str(user_agent or '')
    low = ua.lower()
    browser = ('Edge' if 'edg/' in low else
               'Opera' if 'opr/' in low or 'opera' in low else
               'Samsung Internet' if 'samsungbrowser' in low else
               'Chrome' if 'chrome' in low or 'crios' in low else
               'Firefox' if 'firefox' in low or 'fxios' in low else
               'Safari' if 'safari' in low else '')
    system = ('iPhone' if 'iphone' in low else
              'iPad' if 'ipad' in low else
              'Android' if 'android' in low else
              'Windows' if 'windows' in low else
              'Mac' if 'macintosh' in low or 'mac os' in low else
              'Linux' if 'linux' in low else '')
    if browser and system:
        return f'{browser} on {system}'
    return browser or system or 'Unknown device'


# ── Sessions ────────────────────────────────────────────────────────────────

def start_session(uid: str, user_agent: str = '') -> str:
    sid = new_id()
    now = now_iso()
    execute("""INSERT INTO user_sessions (id, user_id, device, created_at, last_seen)
               VALUES (?,?,?,?,?)""",
            (sid, uid, describe_device(user_agent), now, now), commit=True)
    log_event('signed_in', describe_device(user_agent), uid=uid)
    return sid


def session_is_live(sid: str, uid: str) -> bool:
    """False for a session that was signed out. Called on every request, so it
    stays a single indexed lookup.

    A missing row is treated as LIVE, not dead: tokens minted before sessions
    existed carry no session id at all, and expiring everyone's login to ship a
    feature would be a poor trade. Those sessions simply cannot be listed or
    revoked individually until the next sign-in.
    """
    if not sid:
        return True
    try:
        r = execute("SELECT revoked_at FROM user_sessions WHERE id=? AND user_id=?",
                    (sid, uid), fetchone=True)
    except Exception:
        return True                 # table missing mid-migration: don't lock anyone out
    if not r:
        return True
    return not r.get('revoked_at')


def touch_session(sid: str, uid: str):
    """Update last-seen. Called at most once an hour per session — a write on
    every request would turn a read-mostly app into a write-heavy one for no
    extra precision than "today"."""
    if not sid:
        return
    try:
        r = execute("SELECT last_seen FROM user_sessions WHERE id=? AND user_id=?",
                    (sid, uid), fetchone=True)
        if not r:
            return
        last = dt.datetime.fromisoformat(r['last_seen'])
        if (dt.datetime.now() - last).total_seconds() < 3600:
            return
        execute("UPDATE user_sessions SET last_seen=? WHERE id=? AND user_id=?",
                (now_iso(), sid, uid), commit=True)
    except Exception:
        pass


def list_sessions(current_sid: str = None) -> list:
    uid = current_user_id()
    cutoff = (dt.datetime.now() - dt.timedelta(days=STALE_SESSION_DAYS)).isoformat()
    rows = execute("""SELECT * FROM user_sessions
                      WHERE user_id=? AND revoked_at IS NULL AND last_seen >= ?
                      ORDER BY last_seen DESC""",
                   (uid, cutoff), fetchall=True) or []
    out = []
    for r in rows:
        out.append({'id': r['id'], 'device': r['device'] or 'Unknown device',
                    'created_at': r['created_at'], 'last_seen': r['last_seen'],
                    'current': bool(current_sid and r['id'] == current_sid)})
    return out


def revoke_session(sid: str) -> bool:
    uid = current_user_id()
    r = execute("SELECT device FROM user_sessions WHERE id=? AND user_id=? AND revoked_at IS NULL",
                (sid, uid), fetchone=True)
    if not r:
        return False
    execute("UPDATE user_sessions SET revoked_at=? WHERE id=? AND user_id=?",
            (now_iso(), sid, uid), commit=True)
    log_event('signed_out_device', r['device'] or '')
    return True


def revoke_all_sessions(uid: str = None, keep_sid: str = None) -> int:
    """Sign out everywhere. The caller is also responsible for bumping
    token_version — this table cannot revoke the pre-session tokens."""
    uid = uid or current_user_id()
    rows = execute("""SELECT id FROM user_sessions
                      WHERE user_id=? AND revoked_at IS NULL""", (uid,), fetchall=True) or []
    n = 0
    for r in rows:
        if keep_sid and r['id'] == keep_sid:
            continue
        execute("UPDATE user_sessions SET revoked_at=? WHERE id=?", (now_iso(), r['id']),
                commit=True)
        n += 1
    log_event('signed_out_all', f'{n} devices', uid=uid)
    return n


# ── The log ─────────────────────────────────────────────────────────────────

def log_event(kind: str, detail: str = '', uid: str = None, actor: str = ''):
    """Append one event. Never raises: a failure to write the log must not
    fail the action being logged — a password change that errors because its
    audit line could not be written is worse than an incomplete log."""
    if kind not in EVENT_KINDS:
        return
    try:
        execute("""INSERT INTO security_events (id, user_id, kind, detail, actor, at)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), uid or current_user_id(), kind,
                 str(detail or '')[:200], str(actor or '')[:120], now_iso()),
                commit=True)
    except Exception:
        pass


def list_events(limit: int = 100) -> list:
    rows = execute("""SELECT * FROM security_events WHERE user_id=?
                      ORDER BY at DESC LIMIT ?""",
                   (current_user_id(), max(1, min(int(limit or 100), 500))),
                   fetchall=True) or []
    return [{'id': r['id'], 'kind': r['kind'],
             'label': EVENT_KINDS.get(r['kind'], r['kind']),
             'detail': r['detail'] or '', 'actor': r['actor'] or '',
             'at': r['at']} for r in rows]


# ── Share receipts ──────────────────────────────────────────────────────────

def share_receipts() -> list:
    """Every snapshot link, and what is known about it.

    `views` counts openings, not people: one recipient refreshing twice looks
    the same as two recipients. The number is labelled that way rather than
    presented as an audience count, because a doctor's surgery behind one
    gateway would otherwise read as a crowd.
    """
    uid = current_user_id()
    try:
        rows = execute("""SELECT * FROM share_snapshots WHERE user_id=?
                          ORDER BY created_at DESC""", (uid,), fetchall=True) or []
    except Exception:
        return []
    out = []
    for r in rows:
        d = dict(r)
        out.append({
            'id': d.get('id'),
            'label': d.get('label') or d.get('scope') or 'Share link',
            'scope': d.get('scope'),
            'created_at': d.get('created_at'),
            'expires_at': d.get('expires_at'),
            'revoked': bool(d.get('revoked')),
            'views': d.get('views') or 0,
        })
    return out
