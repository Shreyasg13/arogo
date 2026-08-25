"""
db/dependents.py — family profiles for people who don't use the app themselves.

A caregiver often manages more than one person's health from their own account —
a child's vaccines, an elderly parent's medicines. This is a lightweight,
self-contained sub-system: a `dependents` profile plus flexible typed records
(medicine / vaccine / note / measurement), all owned and scoped to the caregiver.
It deliberately does NOT retrofit the whole app to be multi-profile; a dependent's
data lives only here.
"""
import datetime as _dt

from .core import execute, now_iso, new_id, current_user_id, valid_date

RELATIONSHIPS = ['child', 'parent', 'spouse', 'sibling', 'grandparent', 'other']
RECORD_KINDS = ['medicine', 'vaccine', 'note', 'measurement']
_REL = set(RELATIONSHIPS)
_KIND = set(RECORD_KINDS)


def _clean_rel(r):
    r = str(r or '').strip().lower()
    return r if r in _REL else 'other'


def _owns(dep_id) -> bool:
    """True if the dependent belongs to the current user — the gate every record
    op is checked against, so no one can attach records to someone else's profile."""
    r = execute("SELECT 1 FROM dependents WHERE id=? AND user_id=?",
                (dep_id, current_user_id()), fetchone=True)
    return bool(r)


def _age(birthdate):
    if not birthdate:
        return None
    try:
        b = _dt.date.fromisoformat(birthdate)
    except ValueError:
        return None
    from .core import user_today
    today = _dt.date.fromisoformat(user_today())
    years = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return years if years >= 0 else None


# ── Profiles ─────────────────────────────────────────────────────────────────

def create_dependent(name, relationship='other', birthdate=None, notes='') -> dict:
    name = str(name or '').strip()
    if not name:
        raise ValueError('A name is required')
    bd = birthdate if (birthdate and valid_date(birthdate)) else None
    did = new_id()
    execute("""INSERT INTO dependents (id, name, relationship, birthdate, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (did, name[:80], _clean_rel(relationship), bd, str(notes or '')[:500],
             now_iso(), current_user_id()), commit=True)
    return get_dependent(did)


def update_dependent(dep_id, data) -> dict:
    if not _owns(dep_id):
        raise ValueError('Not found')
    cur = execute("SELECT * FROM dependents WHERE id=? AND user_id=?",
                  (dep_id, current_user_id()), fetchone=True)
    cur = dict(cur)
    name = str(data.get('name', cur['name'])).strip() or cur['name']
    rel = _clean_rel(data.get('relationship', cur['relationship']))
    bd = cur['birthdate']
    if 'birthdate' in data:
        bd = data['birthdate'] if (data['birthdate'] and valid_date(data['birthdate'])) else None
    execute("""UPDATE dependents SET name=?, relationship=?, birthdate=?, notes=?
               WHERE id=? AND user_id=?""",
            (name[:80], rel, bd, str(data.get('notes', cur['notes']))[:500],
             dep_id, current_user_id()), commit=True)
    return get_dependent(dep_id)


def delete_dependent(dep_id) -> bool:
    uid = current_user_id()
    # Remove the profile AND its records (owner-scoped both).
    execute("DELETE FROM dependent_records WHERE dependent_id=? AND user_id=?", (dep_id, uid), commit=True)
    from .trash import soft_delete
    return soft_delete('dependents', dep_id)
    return True


def get_dependent(dep_id) -> dict:
    r = execute("SELECT * FROM dependents WHERE id=? AND user_id=?",
                (dep_id, current_user_id()), fetchone=True)
    if not r:
        return {}
    d = dict(r)
    d['age'] = _age(d.get('birthdate'))
    return d


def list_dependents() -> list:
    rows = execute("""SELECT * FROM dependents WHERE user_id=? ORDER BY created_at""",
                   (current_user_id(),), fetchall=True) or []
    out = []
    for r in rows:
        d = dict(r)
        d['age'] = _age(d.get('birthdate'))
        cnt = execute("""SELECT kind, COUNT(*) c FROM dependent_records
                         WHERE dependent_id=? AND user_id=? GROUP BY kind""",
                      (d['id'], current_user_id()), fetchall=True) or []
        d['counts'] = {row['kind']: row['c'] for row in cnt}
        out.append(d)
    return out


# ── Records ──────────────────────────────────────────────────────────────────

def add_record(dep_id, kind, label, detail='', date_key='') -> dict:
    if not _owns(dep_id):
        raise ValueError('Not found')
    kind = str(kind or '').strip().lower()
    if kind not in _KIND:
        raise ValueError('Unknown record type')
    label = str(label or '').strip()
    if not label:
        raise ValueError('A label is required')
    dk = date_key if (date_key and valid_date(date_key)) else ''
    rid = new_id()
    execute("""INSERT INTO dependent_records (id, dependent_id, kind, label, detail, date_key, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, dep_id, kind, label[:120], str(detail or '')[:300], dk, now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM dependent_records WHERE id=?", (rid,), fetchone=True))


def delete_record(rid) -> bool:
    execute("DELETE FROM dependent_records WHERE id=? AND user_id=?", (rid, current_user_id()), commit=True)
    return True


def get_records(dep_id) -> dict:
    """A dependent's records grouped by kind, newest-first within each group."""
    if not _owns(dep_id):
        raise ValueError('Not found')
    rows = execute("""SELECT * FROM dependent_records WHERE dependent_id=? AND user_id=?
                      ORDER BY (date_key='') , date_key DESC, created_at DESC""",
                   (dep_id, current_user_id()), fetchall=True) or []
    grouped = {k: [] for k in RECORD_KINDS}
    for r in rows:
        grouped.setdefault(r['kind'], []).append(dict(r))
    return {'dependent': get_dependent(dep_id), 'records': grouped, 'total': len(rows)}
