"""
db/today_timeline.py — one hour-by-hour view of *today*.

Stitches the things you log through a single day — medicine doses, vitals, food,
water, sleep, symptoms — into one time-ordered list. Distinct from the multi-week
Health timeline (db/timeline.py), which is a months-long, day-level life-events
log and omits food/water/sleep; this is a single day at clock granularity.

Descriptive only: it repeats what you logged (and, for doses, whether the slot is
taken yet). No judgement of any value.
"""
from __future__ import annotations

from .core import execute, current_user_id, user_today

_VITAL = {
    'blood_pressure': ('❤️', 'Blood pressure', 'mmHg'),
    'blood_sugar':    ('🩸', 'Blood sugar', 'mg/dL'),
    'heart_rate':     ('💓', 'Heart rate', 'bpm'),
    'spo2':           ('🫁', 'Oxygen (SpO₂)', '%'),
    'temperature':    ('🌡️', 'Temperature', '°C'),
    'weight':         ('⚖️', 'Weight', 'kg'),
}


def _hm(iso):
    """HH:MM out of an ISO timestamp, or '' if not parseable."""
    s = str(iso or '')
    if 'T' in s and len(s) >= 16:
        return s[11:16]
    return ''


def get_today_timeline():
    """Today's logged events in clock order. Each: {time, sort, kind, icon,
    title, detail}. `sort` is a HH:MM used for ordering (untimed items sink)."""
    uid = current_user_id()
    today = user_today()
    ev = []

    def add(time, kind, icon, title, detail=''):
        ev.append({'time': time or '', 'sort': time or '99:99',
                   'kind': kind, 'icon': icon, 'title': title, 'detail': detail})

    # Doses (scheduled slots; note whether the slot is taken yet)
    try:
        from .medicines import get_today_doses
        for d in (get_today_doses() or []):
            dose = ' '.join(str(x) for x in [d.get('dosage'), d.get('unit')] if x).strip()
            status = 'taken' if d.get('taken') else 'due'
            detail = (dose + ' · ' if dose else '') + ('✓ ' + 'taken' if d.get('taken') else 'not taken yet')
            add(d.get('time'), 'dose', d.get('icon', '💊'), d.get('med_name', 'Dose'), detail)
    except Exception:
        pass

    # Vitals logged today
    try:
        rows = execute("SELECT * FROM vitals WHERE user_id=? AND date_key=? ORDER BY logged_at",
                       (uid, today), fetchall=True) or []
        for r in rows:
            icon, label, unit = _VITAL.get(r['type'], ('📊', r['type'], r.get('unit') or ''))
            if r['type'] == 'blood_pressure' and r.get('value2') is not None:
                val = f"{_num(r['value1'])}/{_num(r['value2'])} {unit}"
            else:
                val = f"{_num(r['value1'])} {r.get('unit') or unit}".strip()
            add(_hm(r['logged_at']), 'vital', icon, label, val)
    except Exception:
        pass

    # Food logged today
    try:
        rows = execute("SELECT food_name, meal_type, logged_at FROM food_logs WHERE user_id=? AND date_key=? ORDER BY logged_at",
                       (uid, today), fetchall=True) or []
        for r in rows:
            add(_hm(r['logged_at']), 'food', '🍽️', r['food_name'], (r.get('meal_type') or '').replace('_', ' '))
    except Exception:
        pass

    # Water logged today
    try:
        rows = execute("SELECT amount_ml, logged_at FROM hydration_logs WHERE user_id=? AND date_key=? ORDER BY logged_at",
                       (uid, today), fetchall=True) or []
        for r in rows:
            add(_hm(r['logged_at']), 'water', '💧', 'Water', f"{int(r['amount_ml'])} ml")
    except Exception:
        pass

    # Symptoms logged today
    try:
        rows = execute("SELECT name, severity, logged_at FROM symptoms WHERE user_id=? AND date_key=? ORDER BY logged_at",
                       (uid, today), fetchall=True) or []
        for r in rows:
            sev = f"severity {int(r['severity'])}/10" if r.get('severity') is not None else ''
            add(_hm(r['logged_at']), 'symptom', '🤒', r['name'], sev)
    except Exception:
        pass

    # Sleep recorded for today (the night just ended) — shown at wake time
    try:
        r = execute("SELECT bedtime, wake_time, duration_h, quality FROM sleep_logs WHERE user_id=? AND date_key=? ORDER BY created_at DESC LIMIT 1",
                    (uid, today), fetchone=True)
        if r:
            dur = f"{_num(r['duration_h'])} h" if r.get('duration_h') is not None else ''
            add(r.get('wake_time') or '', 'sleep', '😴', 'Woke up', dur)
    except Exception:
        pass

    ev.sort(key=lambda e: e['sort'])
    return {'today': today, 'events': ev, 'count': len(ev)}


def _num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, 1)
    except Exception:
        return v
