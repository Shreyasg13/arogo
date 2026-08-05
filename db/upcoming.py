"""
db/upcoming.py — a forward-looking "what's coming" aggregator.

The health timeline looks backward; this looks forward. It merges the user's own
upcoming appointments, lab rechecks that are due, prescription renewals and
vaccines due — plus any future-dated records logged for dependents — into one
date-sorted list. Everything is derived from real data; nothing is invented, and
past events are excluded.

Titles are returned as raw names + a `type`, so the frontend localizes the
labels (this module has no access to the i18n layer).
"""
import datetime as _dt

from .core import execute, current_user_id, user_today

OVERDUE_FLOOR = 60          # don't surface things overdue by more than this


def _days(d, today):
    try:
        return (_dt.date.fromisoformat(str(d)[:10]) - today).days
    except (ValueError, TypeError):
        return None


def get_upcoming(days=60) -> dict:
    try:
        days = max(1, min(int(days or 60), 365))
    except (TypeError, ValueError):
        days = 60
    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()

    events = []

    def add(date, du, typ, name, detail='', who=''):
        events.append({'date': date, 'days_until': du, 'type': typ,
                       'name': name, 'detail': detail, 'who': who})

    # ── Appointments (upcoming) ───────────────────────────────────
    from .health import list_appointments
    for a in list_appointments(upcoming_only=True):
        du = _days(a['date'], today)
        if du is not None and 0 <= du <= days:
            detail = a.get('time') or ''
            if a.get('location'):
                detail = (detail + ' · ' + a['location']).strip(' ·')
            add(a['date'], du, 'appointment', a['title'], detail)

    # ── Lab rechecks due ──────────────────────────────────────────
    from .labs import get_lab_rechecks
    for r in get_lab_rechecks().get('rechecks', []):
        nd, du = r.get('next_due'), r.get('days_until')
        if nd and du is not None and -OVERDUE_FLOOR <= du <= days:
            add(nd, du, 'lab_recheck', r['name'])

    # ── Prescription renewals ─────────────────────────────────────
    from .prescriptions import list_prescriptions
    for p in list_prescriptions().get('prescriptions', []):
        du = p.get('days_until_expiry')
        if p.get('valid_until') and du is not None and -OVERDUE_FLOOR <= du <= days:
            add(p['valid_until'], du, 'rx_renewal', p.get('prescriber') or '')

    # ── Vaccines due ──────────────────────────────────────────────
    # Use the per-vaccine next_due (not get_record()['due'], which is pre-capped
    # at 60 days) so the window honours the full `days` like the other sources.
    from .immunizations import get_record
    for v in get_record().get('vaccines', []):
        nd = v.get('next_due')
        if nd:
            du = nd.get('days_until')
            if du is not None and -OVERDUE_FLOOR <= du <= days:
                add(nd['date'], du, 'vaccine', v['name'])

    # ── Future-dated dependent records ────────────────────────────
    from .dependents import list_dependents
    uid = current_user_id()
    for dep in list_dependents():
        recs = execute("""SELECT kind, label, date_key FROM dependent_records
                          WHERE dependent_id=? AND user_id=? AND date_key != ''""",
                       (dep['id'], uid), fetchall=True) or []
        for rec in recs:
            du = _days(rec['date_key'], today)
            if du is not None and 0 <= du <= days:
                add(rec['date_key'], du, 'dependent', rec['label'], rec['kind'], dep['name'])

    events.sort(key=lambda e: (e['date'], e['type']))
    return {
        'events': events,
        'days': days,
        'overdue_count': sum(1 for e in events if e['days_until'] < 0),
        'this_week': sum(1 for e in events if 0 <= e['days_until'] <= 7),
    }
