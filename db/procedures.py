"""
db/procedures.py — O1 procedures & hospitalizations log.

The history a new doctor always asks for: past surgeries, hospital stays, and
significant procedures, with dates. Each row is a plain fact the user records —
never interpreted. Scoped to the authenticated user.
"""
from .core import execute, current_user_id, new_id, now_iso, valid_date

KINDS = ('surgery', 'hospitalization', 'procedure')


def _clean(v, limit=160):
    return str(v or '').strip()[:limit]


def add_procedure(data: dict) -> dict:
    name = _clean(data.get('name'))
    if not name:
        raise ValueError('A name is required')
    date_key = str(data.get('date_key') or '').strip()
    if not valid_date(date_key):
        raise ValueError('A valid date is required')
    end_date = str(data.get('end_date') or '').strip()
    if end_date and not valid_date(end_date):
        raise ValueError('End date is not a valid date')
    kind = str(data.get('kind') or '').strip().lower()
    if kind not in KINDS:
        kind = 'procedure'
    pid = new_id()
    execute("""INSERT INTO procedures
               (id, kind, name, date_key, end_date, provider, location, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (pid, kind, name, date_key, end_date or None,
             _clean(data.get('provider')), _clean(data.get('location')),
             _clean(data.get('notes'), 400), now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM procedures WHERE id=?", (pid,), fetchone=True))


def list_procedures() -> list:
    rows = execute("""SELECT * FROM procedures WHERE user_id=?
                      ORDER BY date_key DESC, created_at DESC""",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in (rows or [])]


def delete_procedure(pid: str) -> bool:
    from .trash import soft_delete
    return soft_delete('procedures', pid)
