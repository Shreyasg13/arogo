"""
db/health_notes.py — the "why" behind your record.

A note attached to a specific thing: a medicine ("switched brands — the old one
upset my stomach"), a condition, a doctor, or an appointment ("said recheck in
3 months"). The daily journal captures how a *day* went; this captures why a
*thing* is the way it is, and it stays next to that thing.

HONESTY: notes are the user's own words, stored and shown verbatim. We never
interpret them, never extract "facts" from them, and never surface them as
medical information — they are personal annotations, nothing more. Notes are
never included in any share/export snapshot of the health card.
"""
from __future__ import annotations

from .core import execute, current_user_id, new_id, now_iso

# What a note can be attached to. 'general' = not linked to anything.
ENTITY_TYPES = ('general', 'medicine', 'condition', 'provider', 'appointment', 'lab')
ENTITY_LABEL = {
    'general': 'General', 'medicine': 'Medicine', 'condition': 'Condition',
    'provider': 'Doctor / provider', 'appointment': 'Appointment', 'lab': 'Lab test',
}


def _clean_type(t):
    t = str(t or '').strip().lower()
    return t if t in ENTITY_TYPES else 'general'


def create_note(data):
    body = str((data or {}).get('body') or '').strip()
    if not body:
        raise ValueError('Write something first.')
    nid = new_id()
    execute("""INSERT INTO health_notes
               (id, entity_type, entity_id, entity_label, body, pinned, created_at, updated_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (nid, _clean_type((data or {}).get('entity_type')),
             str((data or {}).get('entity_id') or '')[:64],
             str((data or {}).get('entity_label') or '')[:120],
             body[:4000], 1 if (data or {}).get('pinned') else 0,
             now_iso(), now_iso(), current_user_id()), commit=True)
    return get_note(nid)


def get_note(nid):
    r = execute("SELECT * FROM health_notes WHERE id=? AND user_id=?",
                (nid, current_user_id()), fetchone=True)
    return dict(r) if r else None


def update_note(nid, data):
    cur = get_note(nid)
    if not cur:
        raise ValueError('Note not found')
    body = str(data.get('body', cur['body']) or '').strip() or cur['body']
    execute("""UPDATE health_notes SET body=?, entity_type=?, entity_id=?, entity_label=?,
               pinned=?, updated_at=? WHERE id=? AND user_id=?""",
            (body[:4000], _clean_type(data.get('entity_type', cur['entity_type'])),
             str(data.get('entity_id', cur.get('entity_id')) or '')[:64],
             str(data.get('entity_label', cur.get('entity_label')) or '')[:120],
             1 if data.get('pinned', cur.get('pinned')) else 0,
             now_iso(), nid, current_user_id()), commit=True)
    return get_note(nid)


def delete_note(nid):
    execute("DELETE FROM health_notes WHERE id=? AND user_id=?", (nid, current_user_id()), commit=True)


def list_notes(entity_type=None, entity_id=None, q=None):
    """Pinned first, then newest. Optionally filtered to one entity, or searched."""
    uid = current_user_id()
    sql = "SELECT * FROM health_notes WHERE user_id=?"
    params = [uid]
    if entity_type:
        sql += " AND entity_type=?"
        params.append(_clean_type(entity_type))
    if entity_id:
        sql += " AND entity_id=?"
        params.append(str(entity_id)[:64])
    if q:
        sql += " AND LOWER(body) LIKE ?"
        params.append('%' + str(q).strip().lower() + '%')
    sql += " ORDER BY pinned DESC, updated_at DESC"
    rows = execute(sql, tuple(params), fetchall=True) or []
    return [dict(r) for r in rows]


def notes_for(entity_type, entity_id):
    """The notes attached to one specific thing — for showing inline next to it."""
    if not entity_id:
        return []
    return list_notes(entity_type=entity_type, entity_id=entity_id)
