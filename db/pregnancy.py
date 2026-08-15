"""
db/pregnancy.py — O4 pregnancy tracker.

A place to keep the factual thread of a pregnancy: a profile (last-menstrual-
period or due date, from which the current week is a plain calculation) plus
dated logs of weight and kick counts. Tracking only — Arogo shows the week
number and the user's own logs; it offers NO medical guidance, milestones, or
reassurance, and makes no claim about the pregnancy's progress.
"""
import datetime as _dt

from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today, to_num, to_int

_GEST_DAYS = 280   # 40 weeks from LMP, the standard convention


def _today():
    try:
        return _dt.date.fromisoformat(user_today())
    except ValueError:
        return _dt.date.today()


def get_pregnancy() -> dict:
    """The active pregnancy profile with a computed current week + due date, or
    {active: False} when none is set. Week is derived from LMP when available,
    else back-calculated from the due date; None if neither is a usable date."""
    row = execute("""SELECT * FROM pregnancy WHERE user_id=? AND active=1
                     ORDER BY created_at DESC LIMIT 1""",
                  (current_user_id(),), fetchone=True)
    if not row:
        return {'active': False}
    p = dict(row)
    lmp = p.get('lmp_date')
    due = p.get('due_date')
    week = day = None
    try:
        if lmp:
            delta = (_today() - _dt.date.fromisoformat(lmp)).days
            if delta >= 0:
                week, day = delta // 7, delta % 7
            if not due:
                due = (_dt.date.fromisoformat(lmp) + _dt.timedelta(days=_GEST_DAYS)).isoformat()
        elif due:
            delta = _GEST_DAYS - (_dt.date.fromisoformat(due) - _today()).days
            if delta >= 0:
                week, day = delta // 7, delta % 7
    except (ValueError, TypeError):
        week = day = None
    days_to_due = None
    try:
        if due:
            days_to_due = (_dt.date.fromisoformat(due) - _today()).days
    except (ValueError, TypeError):
        days_to_due = None
    return {'active': True, 'id': p['id'], 'lmp_date': lmp, 'due_date': due,
            'week': week, 'day_in_week': day, 'days_to_due': days_to_due,
            'notes': p.get('notes') or ''}


def set_pregnancy(data: dict) -> dict:
    """Create or replace the active pregnancy profile. Needs at least a valid
    LMP or due date (both optional individually, but one must be present)."""
    lmp = str(data.get('lmp_date') or '').strip()
    due = str(data.get('due_date') or '').strip()
    if lmp and not valid_date(lmp):
        raise ValueError('LMP is not a valid date')
    if due and not valid_date(due):
        raise ValueError('Due date is not a valid date')
    if not lmp and not due:
        raise ValueError('Enter a last-period date or a due date')
    uid = current_user_id()
    execute("UPDATE pregnancy SET active=0 WHERE user_id=? AND active=1", (uid,), commit=True)
    pid = new_id()
    execute("""INSERT INTO pregnancy (id, lmp_date, due_date, active, notes, created_at, user_id)
               VALUES (?,?,?,1,?,?,?)""",
            (pid, lmp or None, due or None, str(data.get('notes') or '').strip()[:300], now_iso(), uid),
            commit=True)
    return get_pregnancy()


def end_pregnancy() -> bool:
    execute("UPDATE pregnancy SET active=0 WHERE user_id=? AND active=1",
            (current_user_id(),), commit=True)
    return True


def add_log(data: dict) -> dict:
    preg = get_pregnancy()
    if not preg.get('active'):
        raise ValueError('No active pregnancy to log against')
    date_key = str(data.get('date_key') or '').strip()
    if not valid_date(date_key):
        date_key = user_today()
    lid = new_id()
    execute("""INSERT INTO pregnancy_logs
               (id, pregnancy_id, date_key, weight_kg, kicks, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (lid, preg['id'], date_key,
             to_num(data.get('weight_kg'), None, lo=20, hi=250),
             to_int(data.get('kicks'), None, lo=0, hi=1000),
             str(data.get('notes') or '').strip()[:300], now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM pregnancy_logs WHERE id=?", (lid,), fetchone=True))


def list_logs() -> list:
    preg = get_pregnancy()
    if not preg.get('active'):
        return []
    rows = execute("""SELECT * FROM pregnancy_logs WHERE user_id=? AND pregnancy_id=?
                      ORDER BY date_key DESC, created_at DESC""",
                   (current_user_id(), preg['id']), fetchall=True)
    return [dict(r) for r in (rows or [])]


def delete_log(lid: str) -> bool:
    execute("DELETE FROM pregnancy_logs WHERE id=? AND user_id=?",
            (lid, current_user_id()), commit=True)
    return True
