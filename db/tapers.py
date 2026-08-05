"""
db/tapers.py — medication tapering schedules.

A taper is a series of dated dose steps for one medicine (e.g. Prednisone 40mg
from Aug 1, 20mg from Aug 8, 10mg from Aug 15…). The step whose start_date is the
latest one on or before today is the dose in effect now. Steps are user- (or
doctor-) entered; nothing is inferred, and the current dose is always derived
from the user's own schedule.
"""
import datetime as _dt

from .core import execute, now_iso, new_id, current_user_id, valid_date, user_today


def _s(v, n=120):
    return str(v or '').strip()[:n]


def _owns_med(mid) -> bool:
    return bool(execute("SELECT id FROM medicines WHERE id=? AND user_id=?",
                        (mid, current_user_id()), fetchone=True))


def add_step(data) -> dict:
    mid = _s(data.get('medicine_id'), 60)
    if not mid or not _owns_med(mid):
        raise ValueError('Unknown medicine')
    dosage = _s(data.get('dosage'), 60)
    if not dosage:
        raise ValueError('A dose is required')
    start = data.get('start_date')
    if not valid_date(start):
        raise ValueError('A valid start date is required')
    sid = new_id()
    execute("""INSERT INTO med_taper_steps (id, medicine_id, dosage, start_date, note, created_at, user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (sid, mid, dosage, start, _s(data.get('note'), 120), now_iso(), current_user_id()),
            commit=True)
    return dict(execute("SELECT * FROM med_taper_steps WHERE id=?", (sid,), fetchone=True))


def delete_step(sid) -> bool:
    execute("DELETE FROM med_taper_steps WHERE id=? AND user_id=?", (sid, current_user_id()), commit=True)
    return True


def get_taper(medicine_id) -> dict:
    """All steps for one medicine, oldest first, each tagged past/current/upcoming.
    'current' = the latest step whose start_date <= today."""
    uid = current_user_id()
    rows = execute("""SELECT * FROM med_taper_steps WHERE medicine_id=? AND user_id=?
                      ORDER BY start_date, created_at""", (medicine_id, uid), fetchall=True) or []
    today = user_today()
    steps = [dict(r) for r in rows]
    # index of the current step: last one with start_date <= today
    cur_idx = None
    for i, s in enumerate(steps):
        if s['start_date'] <= today:
            cur_idx = i
    for i, s in enumerate(steps):
        s['status'] = ('current' if i == cur_idx
                       else 'past' if cur_idx is not None and i < cur_idx
                       else 'upcoming')
        try:
            s['days_until'] = (_dt.date.fromisoformat(s['start_date']) - _dt.date.fromisoformat(today)).days
        except ValueError:
            s['days_until'] = None
    current = steps[cur_idx] if cur_idx is not None else None
    upcoming = next((s for s in steps if s['status'] == 'upcoming'), None)
    return {'steps': steps, 'current': current, 'next': upcoming}


def list_tapers() -> list:
    """One entry per medicine that has a taper: name, current dose, next change."""
    uid = current_user_id()
    meds = execute("""SELECT DISTINCT medicine_id FROM med_taper_steps WHERE user_id=?""",
                   (uid,), fetchall=True) or []
    out = []
    for m in meds:
        mid = m['medicine_id']
        med = execute("SELECT name, icon FROM medicines WHERE id=? AND user_id=?", (mid, uid), fetchone=True)
        if not med:
            continue
        t = get_taper(mid)
        out.append({'medicine_id': mid, 'name': med['name'], 'icon': med['icon'],
                    'current': t['current'], 'next': t['next'], 'step_count': len(t['steps'])})
    out.sort(key=lambda x: x['name'].lower())
    return out
