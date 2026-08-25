"""
db/family_history.py — N3 family medical history.

The question every new doctor asks — "any family history of heart disease,
diabetes, cancer?" — and the one place the app had no answer for. Each entry is
a plain, user-stated fact about a relative: their relation, the condition, an
optional age it started, and a note.

Everything is the user's own record about their family; all queries are
user-scoped. Arogo never turns this into a risk score or a prediction — it just
keeps the facts so they're ready at the next appointment.
"""
from .core import execute, current_user_id, new_id, now_iso, to_int

# Relations offered in the picker; anything else is stored as 'other'.
RELATIONS = ('mother', 'father', 'sister', 'brother', 'daughter', 'son',
             'grandmother', 'grandfather', 'aunt', 'uncle', 'other')


def _clean(v, limit=160):
    return str(v or '').strip()[:limit]


def _clean_relation(v):
    r = str(v or '').strip().lower()
    return r if r in RELATIONS else 'other'


def add_entry(data: dict) -> dict:
    condition = _clean(data.get('condition'))
    if not condition:
        raise ValueError('A condition is required')
    # age_at_onset is optional; None when blank or unparseable, never a fake 0.
    raw_age = data.get('age_at_onset')
    age = None
    if raw_age not in (None, '', 'null'):
        age = to_int(raw_age, None, lo=0, hi=120)
    eid = new_id()
    execute("""INSERT INTO family_history
               (id, relation, condition, age_at_onset, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (eid, _clean_relation(data.get('relation')), condition, age,
             _clean(data.get('notes'), 300), now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM family_history WHERE id=?", (eid,), fetchone=True))


def list_entries() -> list:
    rows = execute("""SELECT * FROM family_history WHERE user_id=?
                      ORDER BY relation, created_at DESC""",
                   (current_user_id(),), fetchall=True)
    return [dict(r) for r in (rows or [])]


def delete_entry(eid: str) -> bool:
    from .trash import soft_delete
    return soft_delete('family_history', eid)
