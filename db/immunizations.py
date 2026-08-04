"""
db/immunizations.py — vaccine dose records + honest "next due" estimates.

Each row is one dose of one vaccine on one date. What's tracked is what you
have; for the few vaccines that recur on a fixed interval (tetanus every 10y,
flu yearly, typhoid every 3y) we estimate the next-due date from the last dose —
always framed as an estimate, never a schedule of our own.
"""
import datetime as _dt

from .core import execute, now_iso, new_id, current_user_id, valid_date
import vaccine_catalog


def log_dose(vaccine_key, date_given, dose_label='', notes='') -> dict:
    if vaccine_key is not None and not isinstance(vaccine_key, (str, int, float)):
        raise ValueError('A vaccine is required')
    vaccine_key = str(vaccine_key or '').strip()
    meta = vaccine_catalog.get_vaccine(vaccine_key)
    if not meta and not vaccine_key:
        raise ValueError('A vaccine is required')
    if not valid_date(date_given):
        raise ValueError('A valid date is required')
    name = meta['name'] if meta else vaccine_key[:80]
    key = meta['key'] if meta else vaccine_key.lower()[:40]
    vid = new_id()
    execute("""INSERT INTO immunizations (id, vaccine_key, name, dose_label, date_given, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (vid, key, name, str(dose_label or '')[:40], date_given,
             str(notes or '')[:300], now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM immunizations WHERE id=?", (vid,), fetchone=True))


def delete_dose(vid) -> bool:
    execute("DELETE FROM immunizations WHERE id=? AND user_id=?", (vid, current_user_id()), commit=True)
    return True


def _next_due(vaccine_key, last_date):
    """For an interval vaccine, estimate the next-due date + overdue flag from the
    last dose. None for one-time vaccines."""
    meta = vaccine_catalog.get_vaccine(vaccine_key)
    if not meta or not meta.get('interval_days') or not last_date:
        return None
    try:
        nxt = _dt.date.fromisoformat(last_date) + _dt.timedelta(days=meta['interval_days'])
    except ValueError:
        return None
    from .core import user_today
    today = _dt.date.fromisoformat(user_today())
    return {'date': nxt.isoformat(),
            'days_until': (nxt - today).days,
            'overdue': nxt < today}


def get_record() -> dict:
    """The user's immunization record: every dose (grouped per vaccine, newest
    dose first) with the catalog metadata + a next-due estimate for recurring
    vaccines. Plus a flat 'due' list of what's overdue or due soon."""
    uid = current_user_id()
    rows = execute("""SELECT * FROM immunizations WHERE user_id=?
                      ORDER BY date_given DESC, created_at DESC""", (uid,), fetchall=True) or []
    by_key = {}
    for r in rows:
        by_key.setdefault(r['vaccine_key'], []).append(dict(r))

    vaccines, due = [], []
    for key, doses in by_key.items():
        meta = vaccine_catalog.get_vaccine(key)
        last = doses[0]['date_given']              # newest first
        nd = _next_due(key, last)
        item = {'key': key, 'name': doses[0]['name'],
                'category': meta['category'] if meta else 'Other',
                'when': meta.get('when') if meta else '',
                'doses': doses, 'dose_count': len(doses),
                'last_date': last, 'next_due': nd}
        vaccines.append(item)
        if nd and nd['days_until'] <= 60:          # overdue or within 2 months
            due.append({'key': key, 'name': item['name'], **nd})
    # Group order follows the catalog's category order for a tidy UI.
    order = {c: i for i, c in enumerate(vaccine_catalog.categories())}
    vaccines.sort(key=lambda v: (order.get(v['category'], 99), v['name']))
    due.sort(key=lambda d: d['days_until'])
    return {'vaccines': vaccines, 'due': due, 'total_doses': len(rows)}


def get_catalog() -> dict:
    grouped = {}
    for v in vaccine_catalog.CATALOG:
        grouped.setdefault(v['category'], []).append(
            {'key': v['key'], 'name': v['name'], 'when': v.get('when', ''),
             'recurring': bool(v.get('interval_days'))})
    return {'categories': vaccine_catalog.categories(), 'vaccines': grouped}
