"""
db/meal_plan.py — plan meals ahead + generate a grocery list.

The food tracker LOGS what was eaten; this PLANS what will be. Assign items to a
day + meal, then roll the plan up into a shopping list that sums quantities of
the same item across the week. Free-text items keep it usable for anything the
food DB doesn't have; quantities are optional.
"""
import datetime as _dt

from .core import execute, now_iso, new_id, current_user_id, valid_date, to_num, user_today

MEAL_TYPES = ('breakfast', 'lunch', 'dinner', 'snack')


def _s(v, n=120):
    return str(v or '').strip()[:n]


def _clean_meal(v):
    v = _s(v, 20).lower()
    return v if v in MEAL_TYPES else 'lunch'


def add_planned(data) -> dict:
    item = _s(data.get('item'), 120)
    if not item:
        raise ValueError('An item is required')
    date = data.get('date')
    if not valid_date(date):
        date = user_today()
    q = data.get('quantity')
    quantity = None if q in (None, '') else to_num(q, 0, lo=0)
    pid = new_id()
    execute("""INSERT INTO meal_plans (id, date, meal_type, item, quantity, unit, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (pid, date, _clean_meal(data.get('meal_type')), item, quantity,
             _s(data.get('unit'), 20), now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM meal_plans WHERE id=?", (pid,), fetchone=True))


def delete_planned(pid) -> bool:
    execute("DELETE FROM meal_plans WHERE id=? AND user_id=?", (pid, current_user_id()), commit=True)
    return True


def get_plan(start=None, days=7) -> dict:
    """The plan for `days` days from `start` (default today), grouped by date then
    meal. Days with nothing planned are still present so the grid is complete."""
    uid = current_user_id()
    try:
        days = max(1, min(int(days or 7), 31))
    except (TypeError, ValueError):
        days = 7
    try:
        start_d = _dt.date.fromisoformat(start) if valid_date(start) else _dt.date.fromisoformat(user_today())
    except ValueError:
        start_d = _dt.date.today()
    end_d = start_d + _dt.timedelta(days=days - 1)
    rows = execute("""SELECT * FROM meal_plans WHERE user_id=? AND date>=? AND date<=?
                      ORDER BY date, created_at""",
                   (uid, start_d.isoformat(), end_d.isoformat()), fetchall=True) or []
    by_date = {}
    for r in rows:
        d = dict(r)
        by_date.setdefault(d['date'], {m: [] for m in MEAL_TYPES})[d['meal_type']].append(d)
    out_days = []
    for i in range(days):
        dk = (start_d + _dt.timedelta(days=i)).isoformat()
        out_days.append({'date': dk, 'meals': by_date.get(dk, {m: [] for m in MEAL_TYPES})})
    return {'start': start_d.isoformat(), 'days': out_days, 'meal_types': list(MEAL_TYPES)}


def get_grocery(start=None, days=7) -> dict:
    """Roll the plan into a shopping list: same item + unit summed across the
    window; unquantified items are listed with an occurrence count."""
    uid = current_user_id()
    try:
        days = max(1, min(int(days or 7), 31))
    except (TypeError, ValueError):
        days = 7
    try:
        start_d = _dt.date.fromisoformat(start) if valid_date(start) else _dt.date.fromisoformat(user_today())
    except ValueError:
        start_d = _dt.date.today()
    end_d = start_d + _dt.timedelta(days=days - 1)
    rows = execute("""SELECT item, quantity, unit FROM meal_plans
                      WHERE user_id=? AND date>=? AND date<=?""",
                   (uid, start_d.isoformat(), end_d.isoformat()), fetchall=True) or []
    agg = {}
    for r in rows:
        key = (r['item'].strip().lower(), (r['unit'] or '').strip().lower())
        a = agg.setdefault(key, {'item': r['item'].strip(), 'unit': (r['unit'] or '').strip(),
                                 'quantity': 0.0, 'qty_count': 0, 'count': 0})
        a['count'] += 1
        if r['quantity'] is not None:
            a['quantity'] += r['quantity']
            a['qty_count'] += 1
    items = []
    for a in agg.values():
        has_qty = a['qty_count'] > 0
        items.append({'item': a['item'], 'unit': a['unit'],
                      'quantity': round(a['quantity'], 2) if has_qty else None,
                      'count': a['count'],
                      # occurrences with no quantity that the summed figure doesn't
                      # cover — so a "Rice 500g" + a bare "Rice" isn't under-bought.
                      'extra': a['count'] - a['qty_count'] if has_qty else 0})
    items.sort(key=lambda x: x['item'].lower())
    return {'items': items, 'total': len(items)}
