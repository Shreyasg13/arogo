"""
db/allergies.py — a structured allergy & reactions log.

Replaces the single free-text allergies box with one row per allergen: what it
is, the reaction it causes, how severe, and when it was noticed. These feed the
Health ID card's allergy line so an emergency reader sees severity, not just a
comma-separated string. User/caregiver-recorded; nothing inferred.
"""
from .core import execute, now_iso, new_id, current_user_id, valid_date

SEVERITIES = ('mild', 'moderate', 'severe')
_SEV_ORDER = {'severe': 0, 'moderate': 1, 'mild': 2}


def _s(v, n=200):
    return str(v or '').strip()[:n]


def _clean_severity(v, default='moderate'):
    v = _s(v, 20).lower()
    return v if v in SEVERITIES else default


def create_allergy(data) -> dict:
    allergen = _s(data.get('allergen'), 120)
    if not allergen:
        raise ValueError('An allergen is required')
    dn = data.get('date_noted')
    dn = dn if (dn and valid_date(dn)) else None
    aid = new_id()
    execute("""INSERT INTO allergies (id, allergen, reaction, severity, date_noted, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (aid, allergen, _s(data.get('reaction'), 200), _clean_severity(data.get('severity')),
             dn, _s(data.get('notes'), 300), now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM allergies WHERE id=?", (aid,), fetchone=True))


def update_allergy(aid, data) -> dict:
    uid = current_user_id()
    row = execute("SELECT * FROM allergies WHERE id=? AND user_id=?", (aid, uid), fetchone=True)
    if not row:
        raise ValueError('Allergy not found')
    row = dict(row)
    allergen = _s(data.get('allergen', row['allergen']), 120) or row['allergen']
    severity = _clean_severity(data.get('severity'), row['severity']) if 'severity' in data else row['severity']
    if 'date_noted' in data:
        dn = data.get('date_noted')
        dn = dn if (dn and valid_date(dn)) else None
    else:
        dn = row['date_noted']
    execute("""UPDATE allergies SET allergen=?, reaction=?, severity=?, date_noted=?, notes=?
               WHERE id=? AND user_id=?""",
            (allergen, _s(data.get('reaction', row['reaction']), 200), severity, dn,
             _s(data.get('notes', row['notes']), 300), aid, uid), commit=True)
    return dict(execute("SELECT * FROM allergies WHERE id=? AND user_id=?", (aid, uid), fetchone=True))


def delete_allergy(aid) -> bool:
    from .trash import soft_delete
    return soft_delete('allergies', aid)
    return True


def list_allergies() -> list:
    """All allergies for the user, most severe first. Read-only."""
    rows = execute("SELECT * FROM allergies WHERE user_id=?", (current_user_id(),), fetchall=True) or []
    items = [dict(r) for r in rows]
    items.sort(key=lambda a: (_SEV_ORDER.get(a['severity'], 1), a['allergen'].lower()))
    return items


def allergy_summary() -> str:
    """A compact 'Penicillin (severe), Peanuts, …' string for cards/exports that
    still want one line. Empty when nothing's logged."""
    parts = []
    for a in list_allergies():
        sev = f" ({a['severity']})" if a['severity'] == 'severe' else ''
        parts.append(f"{a['allergen']}{sev}")
    return ', '.join(parts)
