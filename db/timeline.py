"""
db/timeline.py — one chronological "health story".

A pure read that merges the meaningful dated events from across the app into a
single newest-first list: medicines started, symptoms, vitals, lab results,
appointments, and vaccine doses. Deliberately EXCLUDES the private diary
categories (journal, mood, menstrual cycle) — those are walled elsewhere and
have no business in a shared timeline. Every source query is scoped to the
current user.
"""
from .core import execute, current_user_id
import lab_catalog


# Per-source display metadata for the UI.
TYPES = {
    'medicine':    {'icon': '💊', 'label': 'Medicine'},
    'symptom':     {'icon': '🤒', 'label': 'Symptom'},
    'vital':       {'icon': '❤️', 'label': 'Vital'},
    'lab':         {'icon': '🧪', 'label': 'Lab result'},
    'appointment': {'icon': '📅', 'label': 'Appointment'},
    'vaccine':     {'icon': '💉', 'label': 'Vaccine'},
}

_VITAL_NAMES = {'blood_pressure': 'Blood pressure', 'blood_sugar': 'Blood sugar',
                'heart_rate': 'Heart rate', 'spo2': 'SpO₂', 'temperature': 'Temperature',
                'weight': 'Weight'}


def _ev(date, etype, title, detail=''):
    return {'date': date, 'type': etype, 'title': title, 'detail': detail}


def get_timeline(limit: int = 120, types=None) -> dict:
    """Merged, newest-first events. `types` optionally filters to a subset of
    TYPES keys. `limit` caps the returned list (after the merge + sort)."""
    uid = current_user_id()
    want = set(types) if types else set(TYPES)
    ev = []

    if 'medicine' in want:
        # Date the event by when the medicine was STARTED (user can backdate a
        # drug they've been on for years), falling back to the row's created_at.
        for r in execute("""SELECT name, dosage, purpose,
                                   substr(COALESCE(NULLIF(start_date,''), created_at),1,10) AS d
                            FROM medicines WHERE user_id=?""", (uid,), fetchall=True) or []:
            detail = ' · '.join(x for x in (r['dosage'], r['purpose']) if x)
            ev.append(_ev(r['d'], 'medicine', f"Started {r['name']}", detail))

    if 'symptom' in want:
        for r in execute("""SELECT name, severity, date_key FROM symptoms WHERE user_id=?""",
                         (uid,), fetchall=True) or []:
            ev.append(_ev(r['date_key'], 'symptom', r['name'],
                          f"severity {r['severity']}/10" if r['severity'] else ''))

    if 'vital' in want:
        for r in execute("""SELECT type, value1, value2, unit, date_key FROM vitals WHERE user_id=?""",
                         (uid,), fetchall=True) or []:
            val = f"{r['value1']}/{r['value2']}" if r['value2'] is not None else f"{r['value1']}"
            ev.append(_ev(r['date_key'], 'vital', _VITAL_NAMES.get(r['type'], r['type']),
                          f"{val} {r['unit'] or ''}".strip()))

    if 'lab' in want:
        for r in execute("""SELECT lab_key, name, value, unit, date_key FROM lab_results WHERE user_id=?""",
                         (uid,), fetchall=True) or []:
            st = lab_catalog.status_for(r['lab_key'], r['value'])
            flag = {'low': ' ↓', 'high': ' ↑'}.get(st, '')
            ev.append(_ev(r['date_key'], 'lab', r['name'],
                          f"{r['value']} {r['unit'] or ''}{flag}".strip()))

    if 'appointment' in want:
        for r in execute("""SELECT title, kind, date, location FROM appointments WHERE user_id=?""",
                         (uid,), fetchall=True) or []:
            ev.append(_ev(r['date'], 'appointment', r['title'],
                          ' · '.join(x for x in (r['kind'], r['location']) if x)))

    if 'vaccine' in want:
        for r in execute("""SELECT name, dose_label, date_given FROM immunizations WHERE user_id=?""",
                         (uid,), fetchall=True) or []:
            ev.append(_ev(r['date_given'], 'vaccine', r['name'], r['dose_label'] or ''))

    # Newest first; stable so same-day events keep insertion order.
    ev = [e for e in ev if e['date']]
    ev.sort(key=lambda e: e['date'], reverse=True)
    return {'events': ev[:limit], 'total': len(ev),
            'types': [{'key': k, **v} for k, v in TYPES.items()]}
