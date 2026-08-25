"""
db/expenses.py — out-of-pocket health spending.

India-first: most healthcare is paid out of pocket, so what matters is the net
you actually spent (amount − what a scheme/insurance covered). Each row is one
expense on one date, in one category. Totals are always derived, never stored.
Currency is the app's rupee; amounts are plain numbers (no locale in the DB).
"""
import datetime as _dt
import math

from .core import execute, now_iso, new_id, current_user_id, valid_date

# Fixed category vocabulary — keeps the monthly breakdown tidy and analysable.
CATEGORIES = ['medicines', 'consultation', 'lab', 'hospital', 'insurance', 'other']
_CAT = set(CATEGORIES)


def _clean_cat(c):
    c = str(c or '').strip().lower()
    return c if c in _CAT else 'other'


def _num(v, default=0.0):
    try:
        n = float(v)
        return n if math.isfinite(n) and n >= 0 else default
    except (TypeError, ValueError):
        return default


def log_expense(category, amount, date_key, description='', covered=0, notes='') -> dict:
    amt = _num(amount, None)
    if amt is None or amt <= 0:
        raise ValueError('A positive amount is required')
    cov = min(_num(covered, 0), amt)          # you can't be reimbursed more than you paid
    if not valid_date(date_key):
        from .core import today_iso
        date_key = today_iso()
    eid = new_id()
    execute("""INSERT INTO health_expenses
               (id, date_key, category, description, amount, covered, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (eid, date_key, _clean_cat(category), str(description or '')[:120],
             round(amt, 2), round(cov, 2), str(notes or '')[:300], now_iso(), current_user_id()),
            commit=True)
    return _row(execute("SELECT * FROM health_expenses WHERE id=?", (eid,), fetchone=True))


def delete_expense(eid) -> bool:
    from .trash import soft_delete
    return soft_delete('health_expenses', eid)
    return True


def _row(r):
    d = dict(r)
    d['net'] = round((d['amount'] or 0) - (d['covered'] or 0), 2)
    return d


def _month_bounds(month):
    """month = 'YYYY-MM' → (first_day, last_day) iso strings. Defaults to now's
    month; caller passes a real month so we never call Date.now() server-side."""
    try:
        y, m = map(int, str(month).split('-'))
        first = _dt.date(y, m, 1)
    except (ValueError, AttributeError):
        raise ValueError('month must be YYYY-MM')
    nxt = _dt.date(y + (m == 12), (m % 12) + 1, 1)
    last = nxt - _dt.timedelta(days=1)
    return first.isoformat(), last.isoformat()


def get_month(month) -> dict:
    """One month's expenses + a derived summary: totals, per-category split, and
    what a scheme/insurance covered vs your net out-of-pocket."""
    lo, hi = _month_bounds(month)
    rows = execute("""SELECT * FROM health_expenses
                      WHERE user_id=? AND date_key >= ? AND date_key <= ?
                      ORDER BY date_key DESC, created_at DESC""",
                   (current_user_id(), lo, hi), fetchall=True) or []
    items = [_row(r) for r in rows]

    total = round(sum(i['amount'] for i in items), 2)
    covered = round(sum(i['covered'] for i in items), 2)
    by_cat = {}
    for i in items:
        by_cat[i['category']] = round(by_cat.get(i['category'], 0) + i['net'], 2)
    # Ordered, non-empty categories, largest net first.
    breakdown = sorted(({'category': c, 'net': n} for c, n in by_cat.items() if n),
                       key=lambda x: x['net'], reverse=True)
    return {'month': month, 'items': items,
            'total': total, 'covered': covered,
            'out_of_pocket': round(total - covered, 2),
            'breakdown': breakdown, 'count': len(items)}


def recent_months(n=6) -> list:
    """Net out-of-pocket per month for the last n months that have any expense —
    for a small bar trend. Uses the user's stored dates, not server time."""
    rows = execute("""SELECT substr(date_key,1,7) AS ym,
                             SUM(amount) AS total, SUM(covered) AS covered
                      FROM health_expenses WHERE user_id=?
                      GROUP BY ym ORDER BY ym DESC LIMIT ?""",
                   (current_user_id(), n), fetchall=True) or []
    out = [{'month': r['ym'],
            'out_of_pocket': round((r['total'] or 0) - (r['covered'] or 0), 2)}
           for r in rows]
    return list(reversed(out))     # oldest → newest for the chart
