"""
db/injections.py — J1 injection-site rotation tracker. For people on injectable
medicines (insulin, GLP-1s, biologics, fertility meds), logging which site was
used lets Arogo suggest the least-recently-used site next, so tissue gets a rest
and absorption stays even.

Everything is the user's own log. The "suggested next site" is a plain
least-recently-used pick across a fixed set of body sites — no clinical claim.
"""
import datetime as _dt

from .core import execute, current_user_id, user_today, valid_date, new_id, now_iso

# Fixed set of common subcutaneous/IM injection sites (left/right paired).
INJECTION_SITES = (
    'abdomen_left', 'abdomen_right',
    'thigh_left', 'thigh_right',
    'arm_left', 'arm_right',
    'buttock_left', 'buttock_right',
)


def _clean_site(v) -> str:
    s = str(v or '').strip().lower()
    return s if s in INJECTION_SITES else ''


def log_injection(data: dict) -> dict:
    site = _clean_site(data.get('site'))
    if not site:
        raise ValueError('A valid injection site is required')
    date_key = data.get('date_key')
    if not date_key or not valid_date(date_key):
        date_key = user_today()
    iid = new_id()
    # If a medicine is linked, it must be the caller's own (defence-in-depth,
    # mirroring log_effectiveness — never trust a client-supplied foreign id).
    mid = data.get('medicine_id') or None
    if mid and not execute("SELECT 1 FROM medicines WHERE id=? AND user_id=?",
                           (mid, current_user_id()), fetchone=True):
        mid = None
    execute("""INSERT INTO injection_logs (id, medicine_id, site, date_key, notes, logged_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (iid, mid, site, date_key, str(data.get('notes', ''))[:200], now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM injection_logs WHERE id=?", (iid,), fetchone=True))


def delete_injection(iid: str) -> bool:
    execute("DELETE FROM injection_logs WHERE id=? AND user_id=?",
            (iid, current_user_id()), commit=True)
    return True


def get_injection_state(days: int = 30) -> dict:
    """Per-site last-used date + recent count, the least-recently-used suggestion
    for the next injection, and the recent log. A site never used sorts ahead of
    any used site (it's the freshest choice)."""
    uid = current_user_id()
    days = max(1, min(int(days or 30), 3650))
    start = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()

    # last_used is ALL-TIME (a site injected before the window is still "used", not
    # "never used", and its true last-use date drives the rotation suggestion).
    last_used = {}
    for r in (execute("""SELECT site, MAX(date_key) last FROM injection_logs
                         WHERE user_id=? GROUP BY site""", (uid,), fetchall=True) or []):
        last_used[r['site']] = r['last']
    # count is the recent (windowed) usage, for the "how often lately" display.
    recent_count = {}
    for r in (execute("""SELECT site, COUNT(*) c FROM injection_logs
                         WHERE user_id=? AND date_key>=? GROUP BY site""",
                      (uid, start), fetchall=True) or []):
        recent_count[r['site']] = r['c']

    sites = []
    for s in INJECTION_SITES:
        sites.append({'site': s, 'last_used': last_used.get(s), 'count': recent_count.get(s, 0)})

    # Suggest the least-recently-used: never-used first (last_used None), then the
    # oldest last_used. Stable order within ties follows INJECTION_SITES.
    suggestion = min(sites, key=lambda x: (x['last_used'] is not None, x['last_used'] or ''))

    recent = [dict(r) for r in (execute(
        """SELECT * FROM injection_logs WHERE user_id=? ORDER BY date_key DESC, logged_at DESC LIMIT 20""",
        (uid,), fetchall=True) or [])]

    return {'sites': sites,
            'suggested_next': suggestion['site'],
            'total': sum(s['count'] for s in sites),
            'has_data': bool(last_used) or bool(recent),   # any history, not just the window
            'recent': recent}
