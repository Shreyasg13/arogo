"""
db/ask.py — a private, deterministic "ask your health" assistant.

Answers plain questions about the user's OWN data — "when did I last log my
blood pressure?", "what's my average sleep?", "am I due for any labs?" — with NO
LLM, no cloud, and no fabrication. It matches an intent, reads the answer from
existing aggregate helpers, and states it plainly. When nothing matches, or the
data isn't there, it says so rather than guessing.

Honesty: it only ever reports what you logged (values, dates, counts). It never
interprets a reading ("your BP is high"), never advises, never verdicts. Every
handler returns matched=False if it can't answer, so the caller falls through to
an honest "I can't answer that from your logs" with suggestions.
"""
from __future__ import annotations

import re
import datetime as dt

from .core import execute, current_user_id, user_today


def _ago(days):
    if days is None:
        return ''
    if days <= 0:
        return 'today'
    if days == 1:
        return 'yesterday'
    return f'{days} days ago'


# Question keyword → the data_trust freshness key + a friendly noun.
_LAST_KW = [
    (r'blood pressure|\bbp\b|pressure', 'vitals', 'blood pressure'),
    (r'blood sugar|sugar|glucose', 'vitals', 'blood sugar'),
    (r'heart rate|pulse', 'vitals', 'heart rate'),
    (r'oxygen|spo2|sats?\b', 'vitals', 'oxygen'),
    (r'\bvital', 'vitals', 'a vital'),
    (r'weight|weigh', 'weight', 'weight'),
    (r'\bsleep', 'sleep', 'sleep'),
    (r'water|hydrat', 'water', 'water'),
    (r'\bfood|\bmeal|\bate\b|eat', 'food', 'food'),
    (r'symptom', 'symptoms', 'a symptom'),
    (r'\bdose|\bpill|medicine|\bmed\b|tablet', 'doses', 'a dose'),
    (r'\blab|\btest|report', 'labs', 'a lab result'),
    (r'workout|exercise|activity|\bwalk|\brun\b|gym', 'activity', 'activity'),
]


def _fail(q):
    return {'matched': False, 'answer': None, 'kind': 'none'}


def _last_appointment():
    return execute("""SELECT title, date FROM appointments
                      WHERE user_id=? AND date <= ? ORDER BY date DESC LIMIT 1""",
                   (current_user_id(), user_today()), fetchone=True)


def _handle_last(q):
    # "last doctor visit / appointment" is its own thing.
    if re.search(r'doctor|appointment|\bvisit', q):
        r = _last_appointment()
        if r:
            d = _days_since(r['date'])
            return {'matched': True, 'kind': 'last',
                    'answer': f"Your last recorded visit was “{r['title']}” on {r['date']} ({_ago(d)})."}
        return {'matched': True, 'kind': 'last', 'answer': "I don't have any past visits recorded."}

    try:
        from .data_trust import get_data_freshness
        fresh = {f['key']: f for f in (get_data_freshness() or [])}
    except Exception:
        fresh = {}
    for pat, key, noun in _LAST_KW:
        if re.search(pat, q):
            f = fresh.get(key)
            if f and f.get('last_date'):
                return {'matched': True, 'kind': 'last',
                        'answer': f"You last logged {noun} on {f['last_date']} ({_ago(f.get('days_since'))})."}
            return {'matched': True, 'kind': 'last',
                    'answer': f"I don't have any {noun} logged yet."}
    return _fail(q)


def _days_since(iso):
    try:
        return (dt.date.fromisoformat(user_today()) - dt.date.fromisoformat(str(iso)[:10])).days
    except Exception:
        return None


def _avg(values):
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _handle_average(q):
    days = 30
    try:
        from .health import get_vitals
    except Exception:
        get_vitals = None

    def vitals_avg(vtype):
        rows = get_vitals(vtype, days) if get_vitals else []
        return rows or []

    if re.search(r'blood pressure|\bbp\b|pressure', q) and get_vitals:
        rows = vitals_avg('blood_pressure')
        s, d = _avg([r['value1'] for r in rows]), _avg([r.get('value2') for r in rows])
        if s and d:
            return {'matched': True, 'kind': 'average',
                    'answer': f"Your average blood pressure over the last {days} days is {round(s)}/{round(d)} mmHg (from {len(rows)} readings)."}
        return {'matched': True, 'kind': 'average', 'answer': "You have no blood-pressure readings in the last 30 days."}
    if re.search(r'blood sugar|sugar|glucose', q) and get_vitals:
        rows = vitals_avg('blood_sugar'); a = _avg([r['value1'] for r in rows])
        return {'matched': True, 'kind': 'average',
                'answer': f"Your average blood sugar over the last {days} days is {round(a)} mg/dL (from {len(rows)} readings)."
                if a else "You have no blood-sugar readings in the last 30 days."}
    if re.search(r'heart rate|pulse', q) and get_vitals:
        rows = vitals_avg('heart_rate'); a = _avg([r['value1'] for r in rows])
        return {'matched': True, 'kind': 'average',
                'answer': f"Your average heart rate over the last {days} days is {round(a)} bpm (from {len(rows)} readings)."
                if a else "You have no heart-rate readings in the last 30 days."}
    if re.search(r'\bsleep', q):
        try:
            from .wellness import get_sleep_logs
            rows = get_sleep_logs(days) or []
            a = _avg([r['duration_h'] for r in rows])
            return {'matched': True, 'kind': 'average',
                    'answer': f"You slept an average of {a} hours a night over your last {len(rows)} recorded nights."
                    if a else "You have no sleep logged in the last 30 days."}
        except Exception:
            return _fail(q)
    if re.search(r'weight|weigh', q):
        rows = execute("""SELECT weight_kg FROM body_metrics WHERE user_id=? AND date_key>=?
                          AND weight_kg IS NOT NULL ORDER BY date_key""",
                       (current_user_id(), _cutoff(days)), fetchall=True) or []
        a = _avg([r['weight_kg'] for r in rows])
        return {'matched': True, 'kind': 'average',
                'answer': f"Your average logged weight over the last {days} days is {a} kg (from {len(rows)} entries)."
                if a else "You have no weight entries in the last 30 days."}
    return _fail(q)


def _cutoff(days):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=days - 1)).isoformat()


def _handle_due(q):
    if re.search(r'\blab|\btest|recheck', q):
        try:
            from .labs import get_lab_rechecks
            due = [x for x in (get_lab_rechecks() or {}).get('rechecks', []) if x.get('status') in ('due', 'soon')]
            if due:
                names = ', '.join(x['name'] for x in due[:6])
                return {'matched': True, 'kind': 'due', 'answer': f"These labs look due or coming up: {names}."}
            return {'matched': True, 'kind': 'due', 'answer': "Nothing is flagged as due for a lab recheck right now."}
        except Exception:
            return _fail(q)
    if re.search(r'refill|run(ning)? (low|out)|reorder|pharmacy', q):
        try:
            from .medicines import get_refill_list
            low = [r['name'] for r in (get_refill_list() or []) if not r.get('ordered')]
            if low:
                return {'matched': True, 'kind': 'due', 'answer': f"Running low or due for a refill: {', '.join(low[:6])}."}
            return {'matched': True, 'kind': 'due', 'answer': "No medicines are flagged as running low right now."}
        except Exception:
            return _fail(q)
    if re.search(r'appointment|checkup|visit|doctor|vaccine', q):
        return _handle_next_appt(q)
    return _fail(q)


def _handle_next_appt(q):
    try:
        from .health import get_next_appointment
        a = get_next_appointment()
        if a:
            when = a['date'] + (f" at {a['time']}" if a.get('time') else '')
            return {'matched': True, 'kind': 'appointment',
                    'answer': f"Your next appointment is “{a['title']}” on {when}."}
        return {'matched': True, 'kind': 'appointment', 'answer': "You have no upcoming appointments booked."}
    except Exception:
        return _fail(q)


def _handle_meds(q):
    try:
        from .medicines import list_medicines
        meds = [m['name'] for m in (list_medicines() or []) if m.get('active')]
        if meds:
            return {'matched': True, 'kind': 'meds',
                    'answer': f"You're currently tracking {len(meds)} medicine{'s' if len(meds) != 1 else ''}: {', '.join(meds[:12])}."}
        return {'matched': True, 'kind': 'meds', 'answer': "You have no active medicines set up."}
    except Exception:
        return _fail(q)


def _handle_adherence(q):
    try:
        from .medicines import get_adherence_stats
        a = get_adherence_stats(30) or {}
        if a.get('total'):
            return {'matched': True, 'kind': 'adherence',
                    'answer': f"Over the last 30 days you've taken {a['pct']}% of your scheduled doses ({a['taken']} of {a['total']})."}
        return {'matched': True, 'kind': 'adherence', 'answer': "There isn't enough dose history yet to work that out."}
    except Exception:
        return _fail(q)


SUGGESTIONS = [
    "When did I last log my blood pressure?",
    "What's my average sleep?",
    "Am I due for any labs?",
    "When is my next appointment?",
    "What medicines am I taking?",
    "How am I doing with my doses?",
]


def answer_question(q):
    """Deterministic intent match over the user's own data. Returns
    {matched, answer, kind, suggestions?}."""
    s = str(q or '').strip().lower()
    if not s:
        return {'matched': False, 'answer': None, 'kind': 'none', 'suggestions': SUGGESTIONS}

    # Order matters: more specific intents first.
    if re.search(r'\bnext\b.*(appointment|visit|doctor|checkup)', s) or re.search(r'when.*(appointment|see the doctor|next visit)', s):
        r = _handle_next_appt(s)
        if r['matched']:
            return r
    if re.search(r'\b(average|avg|mean|typical|usual)\b', s):
        r = _handle_average(s)
        if r['matched']:
            return r
    if re.search(r'\b(due|overdue|need|should i|do i need)\b', s) or re.search(r'refill|run(ning)? (low|out)', s):
        r = _handle_due(s)
        if r['matched']:
            return r
    if re.search(r'\b(last|latest|recent(ly)?)\b', s) or re.search(r'when did i', s):
        r = _handle_last(s)
        if r['matched']:
            return r
    if re.search(r'(what|which).*(medicine|medication|pill|drug|tablet)', s) or re.search(r'my (medicine|medication)', s):
        r = _handle_meds(s)
        if r['matched']:
            return r
    if re.search(r'adherence|(how.*doing.*(dose|med|pill))|missed.*(dose|med)|taking.*(regularly|on time)', s):
        r = _handle_adherence(s)
        if r['matched']:
            return r

    return {'matched': False, 'kind': 'none',
            'answer': "I can only answer from what you've logged, and I couldn't match that. Try one of the examples.",
            'suggestions': SUGGESTIONS}
