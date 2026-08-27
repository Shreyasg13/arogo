"""Rehab — "these exercises, twice a day, for six weeks".

That instruction follows most procedures, most injuries, and most physiotherapy
appointments, and almost nobody tracks it. It is exactly the shape Arogo already
handles well for medicines: a thing with a frequency, a course length, and an
adherence question that gets asked at the next appointment and answered from
memory.

Two rules run through this module.

  The app supplies no exercises. Not a library, not a suggested routine, not a
  progression. What is stored is whatever a physiotherapist actually gave this
  person, typed in by them. An exercise programme is prescribed against a
  specific injury, and a generic one from an app is at best useless.

  It never tells anyone to push on or to stop. `pain_after` is recorded because
  it is the first thing a physiotherapist asks at the next session, and it is
  reported back as the user's own number on their own scale. It is never
  compared to a threshold, never turned into a warning, and never used to
  suggest carrying on. Both of those are clinical calls.

Adherence is reported the way the medicines side reports it: done over
scheduled, with the window stated, and no target. "You are at 60%" is a fact.
"You should be at 90%" is not the app's to say.
"""
from __future__ import annotations

import datetime as dt

from .core import execute, current_user_id, new_id, now_iso, user_today, valid_date

# A plan asks for this many sessions a day. Capped at something a real
# programme could plausibly ask for, so a typo cannot make adherence meaningless.
MAX_TIMES_PER_DAY = 12


def _to_int(v, default=1, lo=1, hi=MAX_TIMES_PER_DAY):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def add_plan(name, reason='', prescribed_by='', times_per_day=1,
             started_on=None, until_date='', instructions='') -> dict:
    uid = current_user_id()
    name = str(name or '').strip()[:200]
    if not name:
        raise ValueError('A plan needs a name.')
    pid = new_id()
    execute("""INSERT INTO rehab_plans
                 (id, user_id, name, reason, prescribed_by, times_per_day,
                  started_on, until_date, instructions, active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
            (pid, uid, name, str(reason or '').strip()[:500],
             str(prescribed_by or '').strip()[:200],
             _to_int(times_per_day),
             started_on if valid_date(started_on) else user_today(),
             until_date if valid_date(until_date) else '',
             str(instructions or '').strip()[:4000], now_iso()),
            commit=True)
    return get_plan(pid)


def get_plan(pid):
    r = execute("SELECT * FROM rehab_plans WHERE id=? AND user_id=?",
                (pid, current_user_id()), fetchone=True)
    return _shape_plan(r) if r else None


def _shape_plan(r) -> dict:
    d = dict(r)
    today = user_today()
    until = d.get('until_date') or ''
    return {
        'id': d['id'], 'name': d['name'],
        'reason': d.get('reason') or '',
        'prescribed_by': d.get('prescribed_by') or '',
        'times_per_day': d.get('times_per_day') or 1,
        'started_on': d['started_on'],
        'until_date': until,
        'instructions': d.get('instructions') or '',
        'active': bool(d.get('active')),
        # "Finished" is a date having passed, not a judgement about recovery.
        'ended': bool(until and until < today),
    }


def list_plans(include_inactive: bool = True) -> list:
    uid = current_user_id()
    if include_inactive:
        rows = execute("""SELECT * FROM rehab_plans WHERE user_id=?
                          ORDER BY active DESC, started_on DESC""",
                       (uid,), fetchall=True) or []
    else:
        rows = execute("""SELECT * FROM rehab_plans WHERE user_id=? AND active=1
                          ORDER BY started_on DESC""", (uid,), fetchall=True) or []
    return [_shape_plan(r) for r in rows]


def update_plan(pid, **fields) -> dict:
    allowed = ('name', 'reason', 'prescribed_by', 'times_per_day',
               'started_on', 'until_date', 'instructions', 'active')
    sets, args = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == 'times_per_day':
            v = _to_int(v)
        elif k in ('started_on', 'until_date'):
            if v != '' and not valid_date(v):
                continue
        elif k == 'active':
            v = 1 if v in (1, True, '1', 'true', 'yes') else 0
        else:
            v = str(v).strip()[:4000]
        sets.append(f'{k}=?')
        args.append(v)
    if not sets:
        return get_plan(pid)
    args += [pid, current_user_id()]
    execute(f"UPDATE rehab_plans SET {', '.join(sets)} WHERE id=? AND user_id=?",
            tuple(args), commit=True)
    return get_plan(pid)


def delete_plan(pid) -> bool:
    from .trash import soft_delete
    return soft_delete('rehab_plans', pid)


# ── Sessions ────────────────────────────────────────────────────────────────

def log_session(plan_id, date_key=None, pain_after=None, notes='') -> dict:
    """Record one completed session.

    A plan that is not the caller's is refused rather than silently creating an
    orphaned log — the ownership check is the whole boundary here.
    """
    uid = current_user_id()
    if not get_plan(plan_id):
        raise ValueError('No such plan.')
    date_key = date_key if valid_date(date_key) else user_today()
    pain = None
    if pain_after not in (None, ''):
        try:
            pain = max(0, min(10, int(pain_after)))
        except (TypeError, ValueError):
            pain = None
    lid = new_id()
    execute("""INSERT INTO rehab_logs (id, user_id, plan_id, date_key, done,
                                       pain_after, notes, created_at)
               VALUES (?,?,?,?,1,?,?,?)""",
            (lid, uid, plan_id, date_key, pain,
             str(notes or '').strip()[:1000], now_iso()),
            commit=True)
    r = execute("SELECT * FROM rehab_logs WHERE id=? AND user_id=?",
                (lid, uid), fetchone=True)
    return _shape_log(r)


def _shape_log(r) -> dict:
    d = dict(r)
    return {'id': d['id'], 'plan_id': d['plan_id'], 'date_key': d['date_key'],
            'pain_after': d.get('pain_after'), 'notes': d.get('notes') or ''}


def list_sessions(plan_id, days: int = 60) -> list:
    since = (dt.date.fromisoformat(user_today())
             - dt.timedelta(days=days)).isoformat()
    rows = execute("""SELECT * FROM rehab_logs
                      WHERE user_id=? AND plan_id=? AND date_key >= ?
                      ORDER BY date_key DESC, created_at DESC""",
                   (current_user_id(), plan_id, since), fetchall=True) or []
    return [_shape_log(r) for r in rows]


def delete_session(lid) -> bool:
    from .trash import soft_delete
    return soft_delete('rehab_logs', lid)


def adherence(plan_id, days: int = 14) -> dict:
    """Sessions done over sessions asked for, in a stated window.

    The window is clipped to the plan itself: counting the days before a plan
    started, or after it ended, as missed sessions would make every finished
    course look abandoned. Returns None for the percentage when the window
    contains no scheduled days at all, rather than dividing by zero into a
    reassuring 100%.
    """
    plan = get_plan(plan_id)
    if not plan:
        return None
    today = dt.date.fromisoformat(user_today())
    start = max(dt.date.fromisoformat(plan['started_on']),
                today - dt.timedelta(days=days - 1))
    end = today
    if plan['until_date']:
        end = min(end, dt.date.fromisoformat(plan['until_date']))
    if end < start:
        return {'plan_id': plan_id, 'days': days, 'scheduled': 0, 'done': 0,
                'pct': None,
                'note': 'This window is outside the plan\'s dates.'}

    n_days = (end - start).days + 1
    scheduled = n_days * (plan['times_per_day'] or 1)
    rows = execute("""SELECT COUNT(*) AS n FROM rehab_logs
                      WHERE user_id=? AND plan_id=? AND date_key >= ? AND date_key <= ?""",
                   (current_user_id(), plan_id, start.isoformat(), end.isoformat()),
                   fetchone=True)
    done = (rows or {}).get('n', 0) or 0
    return {
        'plan_id': plan_id,
        'days': n_days,
        'from': start.isoformat(),
        'to': end.isoformat(),
        'scheduled': scheduled,
        'done': done,
        # Capped at 100: doing extra sessions is not 130% adherence, and a
        # number above 100 reads as a data error rather than as enthusiasm.
        'pct': None if not scheduled else min(100, round(done * 100 / scheduled)),
    }


def pain_trail(plan_id, days: int = 60) -> list:
    """The pain numbers as entered, in date order. No average, no direction.

    Two numbers a fortnight apart are two moments. Turning them into "improving"
    is the sentence someone uses to decide whether to keep going, and it is not
    one this app is in a position to write.
    """
    return [{'date': s['date_key'], 'pain': s['pain_after']}
            for s in reversed(list_sessions(plan_id, days))
            if s['pain_after'] is not None]
