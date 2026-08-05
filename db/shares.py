"""
db/shares.py — time-limited, revocable public health snapshots.

A snapshot is a read-only public link (unguessable token) to a SAFE subset of
the user's data. It EXCLUDES the private-walled categories entirely — no
journal, no cycle, no mood — and everything sensitive that isn't a
doctor-relevant summary field. It expires, and the user can revoke it early.

The public read path (resolve_snapshot → compile_snapshot) is the only place in
the app that returns another context's data without a session, so it is
deliberately narrow: token lookup, expiry+revoked checks, then a curated
allow-list of fields built inside the owner's user_context.
"""
from __future__ import annotations
import secrets
import datetime as dt

from .core import execute, now_iso, new_id, current_user_id, user_context

DEFAULT_DAYS = 7
MAX_DAYS = 90


def create_snapshot(label: str = '', days_valid: int = DEFAULT_DAYS) -> dict:
    uid = current_user_id()
    try:
        days_valid = max(1, min(int(days_valid), MAX_DAYS))
    except (TypeError, ValueError):
        days_valid = DEFAULT_DAYS
    token = secrets.token_urlsafe(24)      # ~192 bits, unguessable
    expires = (dt.datetime.utcnow() + dt.timedelta(days=days_valid)).replace(microsecond=0).isoformat()
    sid = new_id()
    execute("""INSERT INTO share_snapshots (id, token, scope, label, created_at, expires_at, revoked, views, user_id)
               VALUES (?,?,?,?,?,?,0,0,?)""",
            (sid, token, 'summary', str(label or '')[:80], now_iso(), expires, uid), commit=True)
    return _row_to_dict(execute("SELECT * FROM share_snapshots WHERE id=? AND user_id=?", (sid, uid), fetchone=True))


def list_snapshots() -> list:
    """The user's own snapshots, newest first, each tagged active/expired/revoked."""
    rows = execute("""SELECT * FROM share_snapshots WHERE user_id=?
                      ORDER BY created_at DESC""", (current_user_id(),), fetchall=True) or []
    return [_row_to_dict(r) for r in rows]


def revoke_snapshot(sid: str) -> bool:
    execute("UPDATE share_snapshots SET revoked=1 WHERE id=? AND user_id=?",
            (sid, current_user_id()), commit=True)
    return True


def _status(row) -> str:
    if row['revoked']:
        return 'revoked'
    if _is_expired(row['expires_at']):
        return 'expired'
    return 'active'


def _is_expired(expires_at) -> bool:
    try:
        return dt.datetime.utcnow() > dt.datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return True          # unparseable expiry → treat as expired (fail closed)


def _row_to_dict(row) -> dict:
    if not row:
        return {}
    d = dict(row)
    d['status'] = _status(row)
    d.pop('user_id', None)   # never leak the owner id to the client
    return d


def resolve_snapshot(token: str):
    """Public, session-less lookup by token. Returns the owner user_id + snapshot
    meta ONLY when the link is live (exists, not revoked, not expired). None
    otherwise — the caller must map None to 404/410 and reveal nothing."""
    if not token or len(token) < 16:
        return None
    row = execute("SELECT * FROM share_snapshots WHERE token=?", (token,), fetchone=True)
    if not row:
        return None
    if row['revoked'] or _is_expired(row['expires_at']):
        return None
    return {'user_id': row['user_id'], 'id': row['id'], 'expires_at': row['expires_at'],
            'label': row['label']}


def _bump_views(sid: str):
    execute("UPDATE share_snapshots SET views = views + 1 WHERE id=?", (sid,), commit=True)


# Fields the public snapshot is ALLOWED to expose. Anything not built here is,
# by construction, not shared. Journal / cycle / mood are absent by design.
def compile_snapshot(owner_uid: str, snap_id: str = None) -> dict:
    """Build the safe, read-only snapshot for a resolved owner. MUST be given a
    user_id that came from resolve_snapshot(), never from a session."""
    from .health import get_emergency_info, get_habit_stats  # noqa: F401 (health import warms core)
    from .medicines import list_medicines, get_adherence_stats
    from .food import get_profile
    from .health import get_vitals

    with user_context(owner_uid):
        profile = get_profile() or {}
        emg = get_emergency_info() or {}
        urow = execute("SELECT name FROM users WHERE id=?", (owner_uid,), fetchone=True)

        meds = [{'name': m['name'], 'dosage': m.get('dosage'), 'unit': m.get('unit'),
                 'frequency': m.get('frequency'), 'times': m.get('times')}
                for m in list_medicines() if m.get('active')]

        latest = {}
        for v in get_vitals(days=120):
            if v['type'] not in latest:
                latest[v['type']] = {'value1': v['value1'], 'value2': v.get('value2'),
                                     'unit': v.get('unit'), 'date': v.get('date_key')}

        adherence = get_adherence_stats(30)

    if snap_id:
        _bump_views(snap_id)

    # First name only — a shared link needn't carry a full legal name.
    name = (urow['name'] if urow and urow['name'] else '') or ''
    first = name.split()[0] if name else ''

    return {
        'name': first,
        'age': profile.get('age'),
        'gender': profile.get('gender'),
        'blood_type': emg.get('blood_type') or None,
        'conditions': emg.get('conditions') or '',
        'allergies': emg.get('allergies') or '',
        'medications': meds,
        'vitals': latest,
        'adherence_30d': adherence,
        'generated': dt.date.today().isoformat(),
        # No journal, cycle, mood, symptoms, weight history, or contacts — by design.
    }
