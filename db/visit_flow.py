"""
db/visit_flow.py — a cohesive per-appointment visit flow (before / during / after).

Ties together, for ONE appointment, pieces that used to live as separate global
lists: questions pinned to this visit, a compact "bring this up" prep list
(refills + labs due around now), the appointment's own post-visit notes, and
structured action items that came out of the visit.

Honest and descriptive: the prep list reuses the app's existing refill/lab-due
logic — nothing is invented, no advice is given. Every read/write is scoped to
current_user_id(), and an action/question can only attach to the caller's own
appointment.
"""
from __future__ import annotations

from .core import execute, current_user_id, new_id, now_iso, user_today


def _own_appt(aid):
    return execute("SELECT * FROM appointments WHERE id=? AND user_id=?",
                   (aid, current_user_id()), fetchone=True)


# ── Per-visit questions (doctor_questions rows carrying this appointment_id) ──
def list_visit_questions(aid):
    rows = execute("""SELECT * FROM doctor_questions
                      WHERE user_id=? AND appointment_id=?
                      ORDER BY asked, created_at""",
                   (current_user_id(), aid), fetchall=True) or []
    return [dict(r) for r in rows]


# ── Per-visit action items (the structured 'after') ──
def add_visit_action(aid, text):
    t = str(text or '').strip()
    if not t:
        raise ValueError('An action is required')
    if not _own_appt(aid):
        raise ValueError('Appointment not found')
    iid = new_id()
    execute("""INSERT INTO visit_action_items (id, appointment_id, text, done, created_at, user_id)
               VALUES (?,?,?,0,?,?)""",
            (iid, aid, t[:300], now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM visit_action_items WHERE id=? AND user_id=?",
                        (iid, current_user_id()), fetchone=True))


def list_visit_actions(aid):
    rows = execute("""SELECT * FROM visit_action_items
                      WHERE user_id=? AND appointment_id=?
                      ORDER BY done, created_at""",
                   (current_user_id(), aid), fetchall=True) or []
    return [dict(r) for r in rows]


def toggle_visit_action(iid):
    execute("""UPDATE visit_action_items SET done = CASE WHEN done=1 THEN 0 ELSE 1 END
               WHERE id=? AND user_id=?""", (iid, current_user_id()), commit=True)


def delete_visit_action(iid):
    execute("DELETE FROM visit_action_items WHERE id=? AND user_id=?",
            (iid, current_user_id()), commit=True)


def _bring_list():
    """A compact 'bring this up' context for an upcoming visit — reuses the app's
    own refill/lab-due logic, never invents. Returns {refills, labs_due}."""
    try:
        from .medicines import get_refill_list
        refills = [{'name': r['name']} for r in (get_refill_list() or []) if not r.get('ordered')]
    except Exception:
        refills = []
    try:
        from .labs import get_lab_rechecks
        labs_due = [{'name': x['name'], 'status': x['status']}
                    for x in (get_lab_rechecks() or {}).get('rechecks', [])
                    if x.get('status') in ('due', 'soon')]
    except Exception:
        labs_due = []
    return {'refills': refills, 'labs_due': labs_due}


def get_visit_detail(aid):
    """Everything for one appointment's before/during/after flow, or None if the
    appointment isn't the caller's. Fields are whitelisted — no internal columns
    leak into the payload."""
    row = _own_appt(aid)
    if not row:
        return None
    appt = dict(row)
    provider = None
    if appt.get('provider_id'):
        p = execute("SELECT name, specialty, clinic, phone FROM providers WHERE id=? AND user_id=?",
                    (appt['provider_id'], current_user_id()), fetchone=True)
        provider = dict(p) if p else None
    is_past = str(appt.get('date') or '') < user_today()
    return {
        'appointment': {
            'id': appt['id'], 'title': appt['title'], 'kind': appt['kind'],
            'date': appt['date'], 'time': appt.get('time') or '',
            'location': appt.get('location') or '',
            'visit_summary': appt.get('visit_summary') or '',
            'follow_up': appt.get('follow_up') or '',
        },
        'provider': provider,
        'is_past': is_past,
        'questions': [{'id': q['id'], 'question': q['question'], 'asked': bool(q['asked'])}
                      for q in list_visit_questions(aid)],
        'actions': [{'id': a['id'], 'text': a['text'], 'done': bool(a['done'])}
                    for a in list_visit_actions(aid)],
        # Prep context only makes sense before the visit.
        'bring': _bring_list() if not is_past else {'refills': [], 'labs_due': []},
    }
