"""
db/health_reminders.py — D custom health reminders & preventive checklist.

The user's OWN list of health to-dos with a due date and an optional repeat
(annual physical, eye test every 2 years, a self-exam each month, a dental
cleaning). Arogo never recommends a screening schedule — that would be medical
advice; the user sets what and when. Marking a repeating item done rolls its due
date forward by the interval; a one-off item just gets ticked off.

Everything is user-scoped; due/overdue is a plain date comparison.
"""
import datetime as _dt

from .core import execute, current_user_id, new_id, now_iso, valid_date, user_today, to_int


def _today():
    try:
        return _dt.date.fromisoformat(user_today())
    except ValueError:
        return _dt.date.today()


def add_reminder(data: dict) -> dict:
    title = str(data.get('title') or '').strip()[:120]
    if not title:
        raise ValueError('A title is required')
    due = str(data.get('due_date') or '').strip()
    if not valid_date(due):
        raise ValueError('A valid due date is required')
    # repeat_days is optional; None (one-off) when blank/unparseable, never 0.
    repeat = to_int(data.get('repeat_days'), None, lo=1, hi=3650)
    rid = new_id()
    execute("""INSERT INTO health_reminders (id, title, due_date, repeat_days, notes, done, last_done, created_at, user_id)
               VALUES (?,?,?,?,?,0,NULL,?,?)""",
            (rid, title, due, repeat, str(data.get('notes') or '').strip()[:300], now_iso(), current_user_id()),
            commit=True)
    return _decorate(dict(execute("SELECT * FROM health_reminders WHERE id=?", (rid,), fetchone=True)))


def _decorate(r: dict) -> dict:
    days = None
    try:
        days = (_dt.date.fromisoformat(r['due_date']) - _today()).days
    except (ValueError, TypeError):
        days = None
    r['days_until'] = days
    r['overdue'] = (days is not None and days < 0 and not r.get('done'))
    r['recurring'] = r.get('repeat_days') is not None
    return r


def list_reminders(include_done: bool = False) -> list:
    uid = current_user_id()
    if include_done:
        rows = execute("SELECT * FROM health_reminders WHERE user_id=? ORDER BY due_date",
                       (uid,), fetchall=True)
    else:
        rows = execute("SELECT * FROM health_reminders WHERE user_id=? AND done=0 ORDER BY due_date",
                       (uid,), fetchall=True)
    return [_decorate(dict(r)) for r in (rows or [])]


def complete_reminder(rid: str) -> dict:
    """Tick a reminder. A repeating one rolls its due date forward by the
    interval (staying active); a one-off is marked done."""
    row = execute("SELECT * FROM health_reminders WHERE id=? AND user_id=?",
                  (rid, current_user_id()), fetchone=True)
    if not row:
        return {}
    row = dict(row)
    today = user_today()
    if row.get('repeat_days'):
        try:
            base = _dt.date.fromisoformat(row['due_date'])
        except (ValueError, TypeError):
            base = _today()
        # Roll forward from whichever is later (due date or today) so an overdue
        # repeat lands in the future, not immediately overdue again.
        anchor = max(base, _today())
        next_due = (anchor + _dt.timedelta(days=int(row['repeat_days']))).isoformat()
        execute("UPDATE health_reminders SET due_date=?, last_done=? WHERE id=? AND user_id=?",
                (next_due, today, rid, current_user_id()), commit=True)
    else:
        execute("UPDATE health_reminders SET done=1, last_done=? WHERE id=? AND user_id=?",
                (today, rid, current_user_id()), commit=True)
    return _decorate(dict(execute("SELECT * FROM health_reminders WHERE id=?", (rid,), fetchone=True)))


def delete_reminder(rid: str) -> bool:
    execute("DELETE FROM health_reminders WHERE id=? AND user_id=?",
            (rid, current_user_id()), commit=True)
    return True
