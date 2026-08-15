"""
db/quit.py — O2 quit tracker (smoking / alcohol / other).

Tracks a quit date and, from the user's OWN stated baseline, computes how long
they've gone, how many units they've avoided, and how much money that adds up
to. Every number is arithmetic on values the user entered — nothing is invented
or benchmarked against anyone else. If a person relapses, they just reset the
quit date; the app makes no judgement.
"""
import datetime as _dt

from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today, to_num

KINDS = ('smoking', 'alcohol', 'other')


def _clean(v, limit=80):
    return str(v or '').strip()[:limit]


def add_plan(data: dict) -> dict:
    quit_date = str(data.get('quit_date') or '').strip()
    if not valid_date(quit_date):
        raise ValueError('A valid quit date is required')
    kind = str(data.get('kind') or '').strip().lower()
    if kind not in KINDS:
        kind = 'other'
    pid = new_id()
    execute("""INSERT INTO quit_plans
               (id, kind, label, quit_date, baseline_per_day, unit_cost, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, kind, _clean(data.get('label')), quit_date,
             to_num(data.get('baseline_per_day'), None, lo=0, hi=1000),
             to_num(data.get('unit_cost'), None, lo=0, hi=1000000),
             _clean(data.get('notes'), 200), now_iso(), current_user_id()), commit=True)
    return _state(dict(execute("SELECT * FROM quit_plans WHERE id=?", (pid,), fetchone=True)))


def update_plan(pid: str, data: dict) -> dict:
    """Reset the quit date (e.g. after a relapse) or edit the baseline/cost."""
    row = execute("SELECT * FROM quit_plans WHERE id=? AND user_id=?",
                  (pid, current_user_id()), fetchone=True)
    if not row:
        return {}
    row = dict(row)
    quit_date = row['quit_date']
    if 'quit_date' in data:
        q = str(data.get('quit_date') or '').strip()
        if not valid_date(q):
            raise ValueError('A valid quit date is required')
        quit_date = q
    baseline = row['baseline_per_day'] if data.get('baseline_per_day') is None else to_num(data.get('baseline_per_day'), row['baseline_per_day'], lo=0, hi=1000)
    cost = row['unit_cost'] if data.get('unit_cost') is None else to_num(data.get('unit_cost'), row['unit_cost'], lo=0, hi=1000000)
    execute("UPDATE quit_plans SET quit_date=?, baseline_per_day=?, unit_cost=? WHERE id=? AND user_id=?",
            (quit_date, baseline, cost, pid, current_user_id()), commit=True)
    return _state(dict(execute("SELECT * FROM quit_plans WHERE id=?", (pid,), fetchone=True)))


def _state(row: dict) -> dict:
    """Attach the derived streak / units-avoided / money-saved. All computed from
    the user's own quit date, baseline and unit cost; None when a value is unset,
    never a fabricated zero-substitute."""
    try:
        today = _dt.date.fromisoformat(user_today())
    except ValueError:
        today = _dt.date.today()
    try:
        qd = _dt.date.fromisoformat(row['quit_date'])
        days = max(0, (today - qd).days)
    except (ValueError, TypeError):
        days = 0
    baseline = row.get('baseline_per_day')
    cost = row.get('unit_cost')
    units_avoided = round(baseline * days, 1) if baseline is not None else None
    money_saved = round(baseline * cost * days, 2) if (baseline is not None and cost is not None) else None
    return {**row, 'days_free': days, 'units_avoided': units_avoided, 'money_saved': money_saved}


def list_plans() -> list:
    rows = execute("SELECT * FROM quit_plans WHERE user_id=? ORDER BY created_at DESC",
                   (current_user_id(),), fetchall=True) or []
    return [_state(dict(r)) for r in rows]


def delete_plan(pid: str) -> bool:
    execute("DELETE FROM quit_plans WHERE id=? AND user_id=?",
            (pid, current_user_id()), commit=True)
    return True
