"""
db/home_supplies.py — M2 home medical-supplies inventory.

The medicine expiry/refill pattern applied to NON-prescription items: the
first-aid kit and OTC basics (thermometer, BP cuff, bandages, paracetamol,
ORS…). Each item tracks a quantity, an optional expiry, and an optional
restock threshold, so Arogo can nudge when something is low or past its date.

Everything is the user's own inventory; all queries are user-scoped. No medical
claims — an OTC item here is a thing on a shelf, not a treatment recommendation.
"""
import datetime as _dt

from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today, to_int

CATEGORIES = ('first_aid', 'otc', 'device', 'other')


def _clean(v, limit=120):
    return str(v or '').strip()[:limit]


def _clean_category(v):
    c = str(v or '').strip().lower()
    return c if c in CATEGORIES else 'other'


def add_supply(data: dict) -> dict:
    name = _clean(data.get('name'))
    if not name:
        raise ValueError('An item name is required')
    expiry = str(data.get('expiry_date') or '').strip()
    if expiry and not valid_date(expiry):
        raise ValueError('Expiry is not a valid date')
    sid = new_id()
    execute("""INSERT INTO home_supplies
               (id, name, category, quantity, unit, expiry_date, low_at, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, name, _clean_category(data.get('category')),
             to_int(data.get('quantity'), 0, lo=0, hi=100000),
             _clean(data.get('unit'), 30), expiry or None,
             to_int(data.get('low_at'), 0, lo=0, hi=100000),
             _clean(data.get('notes'), 300), now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM home_supplies WHERE id=?", (sid,), fetchone=True))


def update_supply(sid: str, data: dict) -> dict:
    """Patch mutable fields (quantity restock, low threshold, expiry, notes) on
    the caller's own item. Returns {} if it isn't theirs."""
    row = execute("SELECT * FROM home_supplies WHERE id=? AND user_id=?",
                  (sid, current_user_id()), fetchone=True)
    if not row:
        return {}
    row = dict(row)
    qty = row['quantity'] if data.get('quantity') is None else to_int(data.get('quantity'), row['quantity'], lo=0, hi=100000)
    low_at = row['low_at'] if data.get('low_at') is None else to_int(data.get('low_at'), row['low_at'], lo=0, hi=100000)
    expiry = row['expiry_date']
    if 'expiry_date' in data:
        e = str(data.get('expiry_date') or '').strip()
        if e and not valid_date(e):
            raise ValueError('Expiry is not a valid date')
        expiry = e or None
    notes = row['notes'] if data.get('notes') is None else _clean(data.get('notes'), 300)
    execute("""UPDATE home_supplies SET quantity=?, low_at=?, expiry_date=?, notes=?
               WHERE id=? AND user_id=?""",
            (qty, low_at, expiry, notes, sid, current_user_id()), commit=True)
    return dict(execute("SELECT * FROM home_supplies WHERE id=?", (sid,), fetchone=True))


def list_supplies(category: str = None) -> list:
    uid = current_user_id()
    if category in CATEGORIES:
        rows = execute("""SELECT * FROM home_supplies WHERE user_id=? AND category=?
                          ORDER BY LOWER(name)""", (uid, category), fetchall=True)
    else:
        rows = execute("""SELECT * FROM home_supplies WHERE user_id=?
                          ORDER BY category, LOWER(name)""", (uid,), fetchall=True)
    return [dict(r) for r in (rows or [])]


def delete_supply(sid: str) -> bool:
    execute("DELETE FROM home_supplies WHERE id=? AND user_id=?",
            (sid, current_user_id()), commit=True)
    return True


def get_alerts(within_days: int = 60) -> dict:
    """Items that need attention: expired, expiring within the window, or low on
    stock (quantity at or below the item's own restock threshold, when set).
    All derived from the user's own numbers — nothing invented."""
    uid = current_user_id()
    within_days = max(1, min(int(within_days or 60), 3650))
    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()

    expired, expiring, low = [], [], []
    for r in list_supplies():
        exp = r.get('expiry_date')
        if exp:
            try:
                days = (_dt.date.fromisoformat(exp) - today).days
                item = {**r, 'days_left': days}
                if days < 0:
                    expired.append(item)
                elif days <= within_days:
                    expiring.append(item)
            except (ValueError, TypeError):
                pass
        # Low-stock nudge only when the user set a threshold (low_at > 0).
        if (r.get('low_at') or 0) > 0 and (r.get('quantity') or 0) <= r['low_at']:
            low.append(r)
    expired.sort(key=lambda x: x['days_left'])
    expiring.sort(key=lambda x: x['days_left'])
    return {'expired': expired, 'expiring': expiring, 'low': low,
            'total': len(expired) + len(expiring) + len(low)}
