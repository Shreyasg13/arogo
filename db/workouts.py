"""
db/workouts.py — structured strength-training log.

One row per SET (exercise, reps, weight). Sets on the same day for the same
exercise form a session. On top we compute progression: estimated one-rep max
(Epley), top set, and per-session volume, so a user can see whether a lift is
actually going up over weeks — the thing a flat activity feed can't show.

Estimated 1RM is a MODEL, not a measured max: we label it "est." everywhere and
never present it as a number the user actually lifted. All queries are scoped to
current_user_id().
"""
from __future__ import annotations

from .core import execute, now_iso, today_iso, new_id, current_user_id, to_num, to_int, valid_date

UNITS = ('kg', 'lb')


def _exercise_key(name: str) -> str:
    """Normalise an exercise name for grouping — case/space-insensitive so
    'Bench Press', 'bench  press' and 'BENCH PRESS' are one exercise."""
    return ' '.join(str(name or '').lower().split())


def epley_1rm(weight: float, reps: int) -> float:
    """Estimated one-rep max, Epley formula: w · (1 + reps/30). A single rep
    returns the weight itself. Bodyweight sets (weight 0) estimate to 0 — there's
    no load to project, so we don't invent one."""
    w = to_num(weight, 0) or 0
    r = to_int(reps, 0)
    if w <= 0 or r <= 0:
        return 0.0
    if r == 1:
        return round(w, 1)          # a logged single is a measured max, not an estimate
    return round(w * (1 + r / 30.0), 1)


def log_set(data: dict) -> dict:
    exercise = str(data.get('exercise', '') or '').strip()
    if not exercise:
        raise ValueError('An exercise name is required')
    reps = to_int(data.get('reps'), 0, lo=0, hi=1000)
    if reps <= 0:
        raise ValueError('Reps must be a positive number')
    weight = to_num(data.get('weight'), 0, lo=0)
    if weight is None or weight < 0:
        weight = 0
    weight = min(weight, 2000)                       # a sane ceiling; a typo'd 99999kg helps no one
    unit = data.get('unit', 'kg')
    if unit not in UNITS:
        unit = 'kg'
    date_key = data.get('date_key', '') or today_iso()
    if not valid_date(date_key):
        date_key = today_iso()
    sid = new_id()
    execute("""INSERT INTO workout_sets
                 (id, exercise, exercise_key, date_key, reps, weight, unit, notes, created_at, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, exercise[:80], _exercise_key(exercise), date_key, reps, weight, unit,
             str(data.get('notes', '') or '')[:200], now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM workout_sets WHERE id=? AND user_id=?",
                        (sid, current_user_id()), fetchone=True))


def delete_set(sid: str):
    execute("DELETE FROM workout_sets WHERE id=? AND user_id=?",
            (sid, current_user_id()), commit=True)


def list_exercises() -> list:
    """Distinct exercise names this user has logged, most-recent first — for the
    log form's quick-pick, so they don't retype 'Bench Press' every time."""
    rows = execute("""SELECT exercise, MAX(created_at) AS last FROM workout_sets
                      WHERE user_id=? GROUP BY exercise_key ORDER BY last DESC""",
                   (current_user_id(),), fetchall=True) or []
    return [r['exercise'] for r in rows]


def get_workout_log(days: int = 30) -> dict:
    """Recent sets grouped into sessions (one per date+exercise), newest first.
    Each session carries its sets, total volume (Σ reps·weight), top-set weight
    and best estimated 1RM."""
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=max(1, days))).isoformat()
    rows = execute("""SELECT * FROM workout_sets WHERE user_id=? AND date_key >= ?
                      ORDER BY date_key DESC, created_at ASC""",
                   (current_user_id(), start), fetchall=True) or []
    sessions = {}
    order = []
    for r in rows:
        d = dict(r)
        key = (d['date_key'], d['exercise_key'])
        s = sessions.get(key)
        if not s:
            s = {'date_key': d['date_key'], 'exercise': d['exercise'], 'unit': d['unit'],
                 'sets': [], 'volume': 0, 'top_weight': 0, 'best_1rm': 0}
            sessions[key] = s
            order.append(key)
        s['sets'].append({'id': d['id'], 'reps': d['reps'], 'weight': d['weight'], 'notes': d.get('notes', '')})
        s['volume'] += (d['reps'] or 0) * (d['weight'] or 0)
        s['top_weight'] = max(s['top_weight'], d['weight'] or 0)
        s['best_1rm'] = max(s['best_1rm'], epley_1rm(d['weight'], d['reps']))
    out = []
    for key in order:
        s = sessions[key]
        s['volume'] = round(s['volume'], 1)
        out.append(s)
    # order preserves DESC-by-date because rows came in that order and dict
    # insertion order is stable.
    return {'days': days, 'sessions': out, 'has_data': bool(out)}


def get_progression(exercise: str) -> dict:
    """Per-session best estimated-1RM and top weight over time for ONE exercise,
    oldest→newest (chart-ready), plus the all-time bests. Empty if the user has
    never logged that lift."""
    key = _exercise_key(exercise)
    rows = execute("""SELECT * FROM workout_sets WHERE user_id=? AND exercise_key=?
                      ORDER BY date_key ASC, created_at ASC""",
                   (current_user_id(), key), fetchall=True) or []
    if not rows:
        return {'exercise': exercise, 'points': [], 'has_data': False,
                'best_1rm': 0, 'best_weight': 0, 'display_name': exercise}
    by_date = {}
    display_name = dict(rows[-1])['exercise']         # most recent casing
    for r in rows:
        d = dict(r)
        p = by_date.setdefault(d['date_key'], {'date_key': d['date_key'], 'best_1rm': 0,
                                               'top_weight': 0, 'unit': d['unit']})
        p['best_1rm'] = max(p['best_1rm'], epley_1rm(d['weight'], d['reps']))
        p['top_weight'] = max(p['top_weight'], d['weight'] or 0)
    points = [by_date[k] for k in sorted(by_date)]
    best_1rm = max((p['best_1rm'] for p in points), default=0)
    best_weight = max((p['top_weight'] for p in points), default=0)
    return {'exercise': key, 'display_name': display_name, 'points': points,
            'best_1rm': round(best_1rm, 1), 'best_weight': best_weight,
            'unit': points[-1]['unit'] if points else 'kg', 'has_data': True}
