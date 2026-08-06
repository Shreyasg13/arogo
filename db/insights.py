"""
db/insights.py — Notification log, weekly report generator, global search, goal progress.

"""
from .core import execute, executemany, jdump, jload, now_iso, today_iso, new_id, current_user_id

from .medicines import get_low_stock_medicines
from .wellness  import get_thoughts_range
from .fitness   import fitness_stats
from .food      import get_profile, calc_tdee
from .health    import get_habit_stats

def add_notification(ntype: str, title: str, body: str = '', source_id: str = None) -> dict:
    nid = new_id()
    execute("INSERT INTO notification_log (id,type,title,body,source_id,read,created_at,user_id) VALUES (?,?,?,?,?,0,?,?)",
            (nid, ntype, title, body, source_id, now_iso(), current_user_id()), commit=True)
    return dict(execute("SELECT * FROM notification_log WHERE id=?", (nid,), fetchone=True))

def get_notifications(limit: int = 50, unread_only: bool = False) -> list:
    if unread_only:
        rows = execute("SELECT * FROM notification_log WHERE read=0 AND user_id=? ORDER BY created_at DESC LIMIT ?",
                       (current_user_id(), limit), fetchall=True)
    else:
        rows = execute("SELECT * FROM notification_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                       (current_user_id(), limit), fetchall=True)
    return [dict(r) for r in rows]

def mark_notification_read(nid: str):
    execute("UPDATE notification_log SET read=1 WHERE id=? AND user_id=?",
            (nid, current_user_id()), commit=True)

def mark_all_notifications_read():
    execute("UPDATE notification_log SET read=1 WHERE user_id=?",
            (current_user_id(),), commit=True)

def unread_notification_count() -> int:
    r = execute("SELECT COUNT(*) as n FROM notification_log WHERE read=0 AND user_id=?",
                (current_user_id(),), fetchone=True)
    return r['n'] if r else 0

# ── Weekly health report ──────────────────────────────────────────────────────

def get_today_glance() -> dict:
    """A one-line "where things stand today": doses still to take, the soonest
    appointment, how many meds are low, and whether a vital is due to be
    measured. Pure aggregation of the user's own data for a single round-trip —
    each number is real or absent, never padded."""
    from .medicines import get_today_doses, get_low_stock_medicines
    from .health import get_next_appointment, list_measurement_reminders

    doses = get_today_doses() or []
    doses_left = sum(1 for d in doses if not d.get('taken'))

    appt = get_next_appointment()
    next_appt = {'title': appt['title'], 'date': appt['date'], 'kind': appt.get('kind')} if appt else None

    low = get_low_stock_medicines() or []

    # A measurement is "due" if the user set a reminder for it and hasn't logged
    # that vital today — a nudge, not an alarm.
    from .core import current_user_id, user_today
    today = user_today()
    measure_due = []
    for r in (list_measurement_reminders() or []):
        if not r.get('enabled'):
            continue
        logged = execute("""SELECT 1 FROM vitals WHERE user_id=? AND type=? AND date_key=? LIMIT 1""",
                         (current_user_id(), r['kind'], today), fetchone=True)
        if not logged:
            measure_due.append(r['kind'])

    return {
        'doses_left': doses_left,
        'doses_total': len(doses),
        'next_appointment': next_appt,
        'low_stock_count': len(low),
        'measurements_due': measure_due,
        'has_anything': bool(doses_left or next_appt or low or measure_due),
    }


def get_visit_prep() -> dict:
    """"Since your last doctor visit" pack for the doctor-summary page.

    Anchors on the most recent PAST appointment with kind='doctor', then shows
    what has actually changed since: vitals that moved (baseline nearest the
    visit vs latest), labs recorded after it, and medicines started/stopped.
    Everything is the user's own data; nothing is computed if the anchor or a
    comparison point is missing (returns None/empty, never a fabricated delta).
    """
    uid = current_user_id()
    today = today_iso()

    row = execute("""SELECT date, title FROM appointments
                     WHERE user_id=? AND kind='doctor' AND date <= ?
                     ORDER BY date DESC LIMIT 1""", (uid, today), fetchone=True)
    if not row:
        return {'last_visit': None, 'vitals_changes': [], 'new_labs': [],
                'med_changes': [], 'has_data': False}
    visit = row['date']

    # Vitals that moved: per type, the reading nearest on-or-before the visit
    # (baseline) vs the newest reading. Only report when there's a genuinely
    # newer reading than the baseline — otherwise there's no "change since".
    vrows = execute("""SELECT type, value1, value2, unit, date_key FROM vitals
                       WHERE user_id=? ORDER BY date_key DESC, logged_at DESC""",
                    (uid,), fetchall=True) or []
    latest, baseline = {}, {}
    for r in vrows:
        vt = r['type']
        if vt not in latest:
            latest[vt] = dict(r)
        # newest reading on-or-before the visit = baseline (rows are newest-first)
        if vt not in baseline and r['date_key'] <= visit:
            baseline[vt] = dict(r)
    vitals_changes = []
    for vt, late in latest.items():
        base = baseline.get(vt)
        if not base or base['date_key'] >= late['date_key']:
            continue        # no earlier anchor, or nothing newer since the visit
        vitals_changes.append({
            'type': vt, 'unit': late.get('unit'),
            'from': {'value1': base['value1'], 'value2': base.get('value2'), 'date': base['date_key']},
            'to':   {'value1': late['value1'], 'value2': late.get('value2'), 'date': late['date_key']},
        })

    # Labs recorded since the visit.
    try:
        from .labs import get_latest_by_test
        new_labs = [{'name': l.get('name'), 'value': l.get('value'), 'unit': l.get('unit'),
                     'date': l.get('date_key'), 'status': l.get('status')}
                    for l in get_latest_by_test() if (l.get('date_key') or '') >= visit]
    except Exception:
        new_labs = []

    # Medicines started/stopped since the visit.
    try:
        from .medicines import get_medicine_events
        med_changes = [{'name': e.get('med_name'), 'kind': e.get('kind'), 'date': (e.get('at') or '')[:10]}
                       for e in get_medicine_events(days=3650)
                       if e.get('kind') in ('started', 'stopped', 'deleted')
                       and (e.get('at') or '')[:10] >= visit]
    except Exception:
        med_changes = []

    return {
        'last_visit': {'date': visit, 'title': row['title']},
        'vitals_changes': vitals_changes,
        'new_labs': new_labs,
        'med_changes': med_changes,
        'has_data': bool(vitals_changes or new_labs or med_changes),
    }


def generate_weekly_report() -> dict:
    import datetime as dt
    uid = current_user_id()
    today = dt.date.today()
    week_start = (today - dt.timedelta(days=6)).isoformat()
    today_iso_v = today.isoformat()

    # Sleep
    sleep_rows = execute("SELECT duration_h,quality FROM sleep_logs WHERE date_key >= ? AND date_key <= ? AND user_id=?",
                         (week_start, today_iso_v, uid), fetchall=True)
    avg_sleep = round(sum(r['duration_h'] for r in sleep_rows) / len(sleep_rows), 1) if sleep_rows else None
    avg_sleep_q = round(sum(r['quality'] for r in sleep_rows) / len(sleep_rows), 1) if sleep_rows else None

    # Workouts
    acts = execute("SELECT * FROM fitness_activities WHERE date >= ? AND date <= ? AND user_id=?",
                   (week_start, today_iso_v, uid), fetchall=True)
    workout_days = len(set(r['date'] for r in acts))
    cal_burned   = sum(r['calories'] or 0 for r in acts)

    # Calories eaten
    food = execute("SELECT SUM(calories) as total FROM food_logs WHERE date_key >= ? AND date_key <= ? AND user_id=?",
                   (week_start, today_iso_v, uid), fetchone=True)
    cal_eaten = round(food['total'] or 0, 0)

    # Profile for target
    profile = get_profile()
    targets = calc_tdee(profile)
    # target_calories is None until the profile has weight/height/age/gender
    target_cal_week = targets['target_calories'] * 7 if targets['target_calories'] else None
    cal_adherence = round(cal_eaten / target_cal_week * 100, 1) if target_cal_week else None

    # Habits — completions WITHIN the 7-day window. get_habit_stats() spans 30
    # days, so counting all of done_dates against a *7*-day denominator ran past
    # 100% (e.g. 8 done-days over the month ÷ 7 = 114%). week7 is each habit's
    # last-7-days view, so numerator and denominator share the same window.
    habit_stats = get_habit_stats()
    total_habits = len(habit_stats['habits'])
    habit_done_count = sum(sum(1 for d in h['week7'] if d['done']) for h in habit_stats['habits'])
    habit_possible = total_habits * 7
    habit_pct = min(round(habit_done_count / habit_possible * 100, 1), 100) if habit_possible else None

    # Top symptoms
    sym_rows = execute("""SELECT name, COUNT(*) as cnt FROM symptoms
                          WHERE date_key >= ? AND date_key <= ? AND user_id=?
                          GROUP BY name ORDER BY cnt DESC LIMIT 5""",
                       (week_start, today_iso_v, uid), fetchall=True)
    top_symptoms = [{'name': r['name'], 'count': r['cnt']} for r in sym_rows]

    # Body metrics
    bm = execute("SELECT weight_kg,bmi FROM body_metrics WHERE date_key >= ? AND user_id=? ORDER BY date_key DESC LIMIT 1",
                 (week_start, uid), fetchone=True)

    # Hydration avg
    hyd = execute("""SELECT AVG(daily_total) as avg FROM
                     (SELECT date_key, SUM(amount_ml) as daily_total FROM hydration_logs
                      WHERE date_key >= ? AND date_key <= ? AND user_id=? GROUP BY date_key) AS daily""",
                  (week_start, today_iso_v, uid), fetchone=True)
    avg_hydration = round(hyd['avg'] or 0) if hyd else 0

    # Vitals latest
    vitals_latest = {}
    for vtype in ['blood_pressure','blood_sugar','heart_rate']:
        r = execute("SELECT value1,value2,unit FROM vitals WHERE type=? AND user_id=? ORDER BY logged_at DESC LIMIT 1",
                    (vtype, uid), fetchone=True)
        if r: vitals_latest[vtype] = dict(r)

    return {
        'period': {'start': week_start, 'end': today_iso_v},
        'sleep':   {'avg_hours': avg_sleep, 'avg_quality': avg_sleep_q, 'nights': len(sleep_rows)},
        'fitness': {'workout_days': workout_days, 'calories_burned': cal_burned, 'activities': len(acts)},
        'nutrition':{'calories_eaten': cal_eaten, 'target': targets['target_calories'],
                     'weekly_target': target_cal_week, 'adherence_pct': cal_adherence,
                     'avg_hydration_ml': avg_hydration},
        'habits':  {'total': total_habits, 'completion_pct': habit_pct, 'done_count': habit_done_count},
        'symptoms': top_symptoms,
        'body':    {'weight_kg': bm['weight_kg'] if bm else None, 'bmi': bm['bmi'] if bm else None},
        'vitals':  vitals_latest,
        'profile': {'name': profile.get('name','User'), 'goal': profile.get('goal','maintain')},
    }

def generate_health_review(days: int = 7) -> dict:
    """A richer, on-screen recap for a chosen window (weekly or monthly): the
    things the plain weekly report leaves out — medication adherence, which way
    the vitals are trending, goal progress, and honest 'wins'. Read-only; every
    number comes from the user's own logs (None where there isn't the data).

    Separate from generate_weekly_report() so the digest email path is untouched.
    """
    import datetime as dt
    from db.goals import list_goals
    from db.medicines import get_adherence_stats

    uid = current_user_id()
    days = 30 if int(days or 7) >= 30 else 7
    today = dt.date.today()
    start = (today - dt.timedelta(days=days - 1)).isoformat()
    end = today.isoformat()

    # ── Medication adherence over the window ──────────────────────
    adh = get_adherence_stats(days=days)
    adherence = adh if adh.get('total') else None

    # ── Sleep + hydration averages ────────────────────────────────
    srows = execute("SELECT duration_h FROM sleep_logs WHERE date_key>=? AND date_key<=? AND user_id=?",
                    (start, end, uid), fetchall=True) or []
    avg_sleep = round(sum(r['duration_h'] for r in srows) / len(srows), 1) if srows else None
    hyd = execute("""SELECT AVG(daily) a FROM (SELECT date_key, SUM(amount_ml) daily FROM hydration_logs
                     WHERE date_key>=? AND date_key<=? AND user_id=? GROUP BY date_key) t""",
                  (start, end, uid), fetchone=True)
    avg_hydration = round(hyd['a']) if hyd and hyd['a'] else None

    # ── Vitals with a direction (needs enough readings to judge) ──
    vitals = _vitals_directions(uid, start, end)

    # ── Goal progress (active goals only) ─────────────────────────
    goals = []
    for g in list_goals().get('goals', []):
        goals.append({
            'title': g.get('title') or g.get('metric_name'),
            'metric_name': g.get('metric_name'), 'unit': g.get('unit'),
            'target': g.get('target_value'), 'current': g.get('current'),
            'progress': g.get('progress'), 'achieved': g.get('auto_achieved'),
        })

    # ── Top symptoms in the window ────────────────────────────────
    sym = execute("""SELECT name, COUNT(*) c FROM symptoms WHERE date_key>=? AND date_key<=? AND user_id=?
                     GROUP BY name ORDER BY c DESC LIMIT 5""", (start, end, uid), fetchall=True) or []
    symptoms = [{'name': r['name'], 'count': r['c']} for r in sym]

    profile = get_profile()
    goal = (profile.get('goal') or '')

    # ── Wins: only statements the data actually supports ──────────
    # Each win needs enough underlying data to be honest — a single logged night
    # or a lone dose must never become "you averaged 8h" / "you took 100%".
    wins = []
    if adherence and adherence['pct'] >= 90 and adherence['total'] >= 5:
        wins.append({'icon': '💊', 'text': f"Took {adherence['pct']}% of your scheduled doses"})
    if avg_sleep is not None and avg_sleep >= 7 and len(srows) >= 4:
        wins.append({'icon': '😴', 'text': f"Averaged {avg_sleep} h of sleep a night"})
    for g in goals:
        if g['achieved']:
            wins.append({'icon': '🎯', 'text': f"Reached your goal: {g['title']}"})
    for v in vitals:
        if v['direction'] != 'down':
            continue
        # BP/sugar down is generically good; weight down is only a "win" if the
        # user is actually trying to lose — not for a gain/maintain goal.
        if v['type'] in ('blood_pressure', 'blood_sugar'):
            wins.append({'icon': '📉', 'text': f"{v['label']} trending down"})
        elif v['type'] == 'weight' and goal in ('lose', 'lose_fast'):
            wins.append({'icon': '📉', 'text': f"{v['label']} trending down toward your goal"})

    label = 'Last 30 days' if days == 30 else 'Last 7 days'
    return {
        'period': {'days': days, 'start': start, 'end': end, 'label': label},
        'name': profile.get('name') or 'there',
        'adherence': adherence,
        'sleep': {'avg_hours': avg_sleep, 'nights': len(srows)},
        'hydration_avg_ml': avg_hydration,
        'vitals': vitals,
        'goals': goals,
        'symptoms': symptoms,
        'wins': wins,
    }


def _vitals_directions(uid, start, end):
    """For each vital with enough readings in the window, the latest value and a
    conservative direction (up / down / flat). Below the minimum we return None
    for direction rather than call a trend off two points."""
    specs = [
        ('blood_pressure', 'Blood pressure', 'mmHg', 3.0),
        ('blood_sugar',    'Blood sugar',    'mg/dL', 6.0),
        ('heart_rate',     'Resting heart rate', 'bpm', 3.0),
    ]
    out = []
    for vtype, label, unit, thresh in specs:
        rows = execute("""SELECT value1, value2 FROM vitals WHERE type=? AND user_id=?
                          AND logged_at>=? ORDER BY logged_at ASC""",
                       (vtype, uid, start + 'T00:00:00'), fetchall=True) or []
        vals = [r['value1'] for r in rows if r['value1'] is not None]
        if not vals:
            continue
        latest_row = rows[-1]
        latest = (f"{int(latest_row['value1'])}/{int(latest_row['value2'])}"
                  if vtype == 'blood_pressure' and latest_row['value2'] is not None
                  else _fmt_num(latest_row['value1']))
        direction = None
        if len(vals) >= 4:
            mid = len(vals) // 2
            first, second = sum(vals[:mid]) / mid, sum(vals[mid:]) / (len(vals) - mid)
            diff = second - first
            direction = 'up' if diff > thresh else 'down' if diff < -thresh else 'flat'
        out.append({'type': vtype, 'label': label, 'unit': unit,
                    'latest': latest, 'readings': len(vals), 'direction': direction})
    # Weight from body_metrics
    wrows = execute("""SELECT weight_kg FROM body_metrics WHERE date_key>=? AND date_key<=? AND user_id=?
                       AND weight_kg IS NOT NULL ORDER BY date_key ASC""",
                    (start, end, uid), fetchall=True) or []
    wvals = [r['weight_kg'] for r in wrows]
    if wvals:
        direction = None
        # Mean of the first half vs the second half (same method as the other
        # vitals) — comparing two lone endpoints flips on day-to-day water swings.
        if len(wvals) >= 4:
            mid = len(wvals) // 2
            first, second = sum(wvals[:mid]) / mid, sum(wvals[mid:]) / (len(wvals) - mid)
            diff = second - first
            direction = 'up' if diff > 0.4 else 'down' if diff < -0.4 else 'flat'
        out.append({'type': 'weight', 'label': 'Weight', 'unit': 'kg',
                    'latest': _fmt_num(wvals[-1]), 'readings': len(wvals), 'direction': direction})
    return out


def _fmt_num(v):
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(round(f, 1))
    except (TypeError, ValueError):
        return str(v)


# Per-type "meaningful move" thresholds and labels for the anomaly flags. A
# trend must clear the epsilon end-to-end so a 0.1 wiggle never reads as a trend.
_ANOMALY_SPECS = {
    'blood_pressure': {'label': 'Blood pressure', 'unit': 'mmHg', 'eps': 6},
    'blood_sugar':    {'label': 'Blood sugar',    'unit': 'mg/dL', 'eps': 12},
    'heart_rate':     {'label': 'Resting heart rate', 'unit': 'bpm', 'eps': 5},
    'weight':         {'label': 'Weight', 'unit': 'kg', 'eps': 1.5},
    'spo2':           {'label': 'SpO2', 'unit': '%', 'eps': 2},
    'temperature':    {'label': 'Temperature', 'unit': '', 'eps': 0.6},
}


def get_vitals_anomalies(lookback_days: int = 60, min_run: int = 3, min_trend: int = 4) -> dict:
    """Flag vitals that are on a RUN worth a glance — never a diagnosis:

      • out-of-band: the last >= min_run readings all sit above (or all below)
        the user's own target band (from vital_targets), or
      • trend: the last >= min_trend readings move monotonically one way by more
        than a per-type epsilon end-to-end.

    Only the user's own readings, newest-first per type. Nothing is flagged
    without enough readings, and the copy stays direction-only ("worth
    mentioning"), leaving any judgement to a clinician.
    """
    from db.vital_targets import get_targets, flag
    uid = current_user_id()
    lookback_days = max(7, min(int(lookback_days or 60), 3650))
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    targets = get_targets()
    flags = []

    for vtype, spec in _ANOMALY_SPECS.items():
        rows = execute("""SELECT value1 FROM vitals WHERE type=? AND user_id=? AND date_key>=?
                          ORDER BY date_key DESC, logged_at DESC""",
                       (vtype, uid, start), fetchall=True) or []
        series = [r['value1'] for r in rows if r['value1'] is not None]   # newest-first
        if len(series) < min_run:
            continue

        # (a) Out-of-band run against the user's target band.
        tgt = targets.get(vtype)
        if tgt:
            run, kind = 0, None
            for v in series:
                f = flag(vtype, v, {vtype: tgt})
                if f in ('above', 'below') and (kind is None or f == kind):
                    kind = f
                    run += 1
                else:
                    break
            if run >= min_run:
                flags.append({'type': vtype, 'label': spec['label'], 'unit': spec['unit'],
                              'kind': 'out_of_band', 'direction': kind, 'run': run,
                              'latest': _fmt_num(series[0])})
                continue        # one flag per vital is enough; band beats trend

        # (b) Monotonic trend run (newest-first: diff>0 means the newer reading
        # is higher, i.e. rising over time).
        run, direction = 1, None
        for i in range(1, len(series)):
            d = series[i - 1] - series[i]
            step = 'up' if d > 0 else 'down' if d < 0 else None
            if step is None or (direction and step != direction):
                break
            direction = direction or step
            run += 1
        if run >= min_trend:
            net = abs(series[0] - series[run - 1])
            if net >= spec['eps']:
                flags.append({'type': vtype, 'label': spec['label'], 'unit': spec['unit'],
                              'kind': 'trend', 'direction': direction, 'run': run,
                              'latest': _fmt_num(series[0]), 'net': round(net, 1)})

    return {'flags': flags, 'has_data': bool(flags)}


# ── Weekly digest ─────────────────────────────────────────────────────────────

def _hydration_goal_ml() -> int:
    """The user's own water goal — not a number we made up about them.

    The digest used to hardcode 2450ml and print it as "goal", while the app
    stored whatever the user had actually set one table over. (2450 is itself
    35ml × an assumed 70kg body, which is why it looks specific enough to be
    believed.)
    """
    rs = execute("SELECT water_goal_ml FROM reminder_settings WHERE user_id=?",
                 (current_user_id(),), fetchone=True)
    return (rs or {}).get('water_goal_ml') or 2450


def generate_weekly_digest(lang: str = None) -> dict:
    """Weekly insight digest — scores, highlights, wins, concerns, headline.
    Built on generate_weekly_report(); used by /api/weekly-digest and the
    Sunday digest email job.

    `lang` localizes the prose (headline/wins/concerns/highlight labels). When
    None it resolves to the current user's stored language, so both the in-app
    view and the email speak the user's language. Numbers/units stay as-is."""
    import datetime as dt
    from i18n_server import tr

    if lang is None:
        try:
            from db import get_user_language
            from db.core import current_user_id
            lang = get_user_language(current_user_id())
        except Exception:
            lang = 'en'

    r = generate_weekly_report()
    hydration_goal = _hydration_goal_ml()

    # ── Scores (0-100, or None where there's nothing to score) ────
    #
    # A category the user doesn't track is an ABSENCE, not a zero. These used
    # to default to 0 and always divide by 5, so someone who took every
    # medicine and slept 8h a night but didn't track water, food or habits
    # scored (100+100+0+0+0)/5 = 40 → "Mixed week", and this goes out as an
    # email. Not using a feature is not a failure to report back to someone.
    sleep_score = None
    if r['sleep']['avg_hours']:
        h = r['sleep']['avg_hours']
        sleep_score = min(100, int(min(h, 9) / 9 * 100))
        if r['sleep']['avg_quality']:
            sleep_score = int(sleep_score * 0.7 + (r['sleep']['avg_quality']/5*100) * 0.3)

    # Judge exercise only if they log exercise at all — 0 workout days is
    # indistinguishable from "doesn't use this part of the app".
    workout_score = (min(100, int(r['fitness']['workout_days'] / 5 * 100))
                     if r['fitness']['activities'] else None)

    habit_score = (int(r['habits']['completion_pct'] or 0)
                   if r['habits']['total'] else None)

    hydration_score = None
    if r['nutrition']['avg_hydration_ml']:
        goal = _hydration_goal_ml()
        hydration_score = min(100, int(r['nutrition']['avg_hydration_ml'] / goal * 100))

    cal_score = None
    if r['nutrition']['adherence_pct']:
        pct = r['nutrition']['adherence_pct']
        # Ideal is 90–110% of target
        cal_score = 100 if 90 <= pct <= 110 else max(0, int(100 - abs(pct - 100) * 2))

    tracked = [s for s in (sleep_score, workout_score, habit_score,
                           hydration_score, cal_score) if s is not None]
    overall_score = int(sum(tracked) / len(tracked)) if tracked else None

    # ── Wins ──────────────────────────────────────────────────────
    wins = []
    sleep_h = r['sleep']['avg_hours']
    nights  = r['sleep']['nights']
    # "Averaged" needs something to average. One logged night was being
    # reported identically to seven, with no denominator — so say how many.
    # (get_insight_cards one function below already requires >=4; same bar.)
    enough_nights = nights >= 4
    if sleep_h and enough_nights and sleep_h >= 7:
        wins.append({'icon': '🌙', 'text': tr(lang, 'digest.win_sleep', h=sleep_h, nights=nights)})
    if r['fitness']['workout_days'] >= 4:
        wins.append({'icon': '🏅', 'text': tr(lang, 'digest.win_workouts', days=r['fitness']['workout_days'])})
    if habit_score is not None and habit_score >= 80:
        wins.append({'icon': '⭐', 'text': tr(lang, 'digest.win_habits', pct=int(habit_score))})
    if hydration_score is not None and hydration_score >= 90:
        wins.append({'icon': '💧', 'text': tr(lang, 'digest.win_hydration', ml=r['nutrition']['avg_hydration_ml'])})
    if r['fitness']['calories_burned'] >= 2000:
        wins.append({'icon': '🔥', 'text': tr(lang, 'digest.win_burned', kcal=f"{r['fitness']['calories_burned']:,}")})

    # ── Concerns ──────────────────────────────────────────────────
    concerns = []
    if sleep_h and enough_nights and sleep_h < 6:
        concerns.append({'icon': '😴', 'text': tr(lang, 'digest.concern_sleep_low', h=sleep_h, nights=nights)})
    elif sleep_h and enough_nights and sleep_h < 7:
        concerns.append({'icon': '🌙', 'text': tr(lang, 'digest.concern_sleep_short', h=sleep_h, nights=nights)})

    # Only comment on exercise if they log exercise. "No workouts logged this
    # week" fired unconditionally, so it went to people who have never used
    # fitness tracking and never intend to — a complaint about a feature, not
    # about their week.
    if r['fitness']['activities'] and r['fitness']['workout_days'] <= 1:
        concerns.append({'icon': '🏃', 'text': tr(lang, 'digest.concern_workouts', days=r['fitness']['workout_days'])})

    if habit_score is not None and habit_score < 50 and r['habits']['total'] > 0:
        concerns.append({'icon': '📋', 'text': tr(lang, 'digest.concern_habits', pct=int(habit_score))})

    if r['symptoms']:
        top = r['symptoms'][0]
        concerns.append({'icon': '🩺', 'text': tr(lang, 'digest.concern_symptom', name=top['name'], count=top['count'], s=('s' if top['count']>1 else ''))})

    # This one had no data guard at all, so a user who never logged water was
    # told they "averaged 0ml" — a health claim about someone who simply didn't
    # use the feature — measured against a goal they never set.
    if hydration_score is not None and hydration_score < 60:
        concerns.append({'icon': '💧', 'text': tr(lang, 'digest.concern_hydration', ml=r['nutrition']['avg_hydration_ml'], goal=hydration_goal)})

    # ── Highlights ────────────────────────────────────────────────
    highlights = []
    if r['sleep']['nights'] > 0 and sleep_h:
        # Carry the denominator: 1 night and 7 nights were shown identically.
        highlights.append({'label': tr(lang, 'digest.hl_sleep', nights=nights),
                           'value': f'{sleep_h}h', 'icon': '🌙'})
    if r['fitness']['workout_days'] > 0:
        highlights.append({'label': tr(lang, 'digest.hl_workouts'), 'value': str(r['fitness']['workout_days']),  'icon': '🏋️'})
    if r['habits']['total'] > 0:
        highlights.append({'label': tr(lang, 'digest.hl_habits'),       'value': f'{int(habit_score)}%',             'icon': '⭐'})
    if r['nutrition']['avg_hydration_ml']:
        highlights.append({'label': tr(lang, 'digest.hl_water'),    'value': f'{r["nutrition"]["avg_hydration_ml"]}ml','icon': '💧'})
    if r['fitness']['calories_burned']:
        highlights.append({'label': tr(lang, 'digest.hl_burned'),   'value': f'{r["fitness"]["calories_burned"]:,}',  'icon': '🔥'})

    # ── Headline ──────────────────────────────────────────────────
    # Don't score an empty week as a failure — a brand-new user with nothing
    # logged gets a welcoming prompt, not "Tough week".
    has_data = (
        r['sleep']['nights'] > 0
        or r['fitness']['workout_days'] > 0
        or (r['nutrition']['avg_hydration_ml'] or 0) > 0
        or r['habits'].get('done_count', 0) > 0
        or bool(r['symptoms'])
    )
    if not has_data or overall_score is None:
        headline = tr(lang, 'digest.headline_empty')
        # An empty week has no score and no complaints. The headline was already
        # careful about this; the score ring and the concerns below it weren't,
        # so the friendly sentence sat above a red 0 and two scoldings.
        overall_score = None
        concerns = []
    elif overall_score >= 80:
        headline = tr(lang, 'digest.headline_strong')
    elif overall_score >= 60:
        headline = tr(lang, 'digest.headline_solid')
    elif overall_score >= 40:
        headline = tr(lang, 'digest.headline_mixed')
    else:
        headline = tr(lang, 'digest.headline_tough')

    # ── Period label (portable: %-d is Linux-only) ────────────────
    start = dt.date.fromisoformat(r['period']['start'])
    end   = dt.date.fromisoformat(r['period']['end'])
    period_label = (f"{start.strftime('%b')} {start.day} – "
                    f"{end.strftime('%b')} {end.day}, {end.year}")

    return {
        'period':        r['period'],
        'period_label':  period_label,
        'headline':      headline,
        # None when there's nothing to score. Never 0 — a zero would say "you
        # failed at everything" where the truth is "you didn't track anything".
        'overall_score': overall_score,
        'tracked_areas': len(tracked),
        # Each score is None for an area the user doesn't track, so the UI can
        # leave it out rather than draw an empty bar next to the ones that count.
        'scores': {
            'sleep':      sleep_score,
            'workouts':   workout_score,
            'habits':     habit_score,
            'hydration':  hydration_score,
            'nutrition':  cal_score,
        },
        'highlights':  highlights,
        'wins':        wins[:3],
        'concerns':    concerns[:3],
        'raw':         r,
    }


# ── Insight cards ─────────────────────────────────────────────────────────────

def get_insight_cards(limit: int = 3) -> list:
    """Rules-based dashboard insights. Every rule emits ONLY when there's
    enough real data behind it — a new user simply gets an empty list.
    Tones: success (celebrate), warning (watch out), info (neutral fact)."""
    import datetime as dt
    uid = current_user_id()
    today = dt.date.today()
    d7  = (today - dt.timedelta(days=6)).isoformat()
    d30 = (today - dt.timedelta(days=29)).isoformat()
    cards = []

    def add(icon, text, tone='info'):
        cards.append({'icon': icon, 'text': text, 'tone': tone})

    # 1. Habit streak worth protecting
    try:
        from .health import get_habit_stats
        habits = get_habit_stats()['habits']
        top = max(habits, key=lambda h: h.get('streak', 0)) if habits else None
        if top and top.get('streak', 0) >= 5:
            add('🔥', f"{top['streak']}-day streak on “{top['name']}” — keep it alive today",
                'success')
    except Exception:
        pass

    # 2. Medicine adherence this week (needs ≥5 logged doses)
    r = execute("""SELECT COUNT(*) AS n, SUM(CASE WHEN taken=1 THEN 1 ELSE 0 END) AS t
                   FROM dose_logs WHERE user_id=? AND date_key>=?""", (uid, d7), fetchone=True)
    if r and (r['n'] or 0) >= 5:
        pct = round((r['t'] or 0) / r['n'] * 100)
        if pct >= 90:
            add('💊', f"{pct}% dose adherence this week — excellent consistency", 'success')
        elif pct < 60:
            add('💊', f"Only {pct}% of doses taken this week — worth a look at your reminder times",
                'warning')

    # 3. Sleep on workout days vs rest days (last 30d, ≥4 nights each)
    sleep = {s['date_key']: s['duration_h'] for s in execute(
        "SELECT date_key, duration_h FROM sleep_logs WHERE user_id=? AND date_key>=?",
        (uid, d30), fetchall=True)}
    workout_days = {a['date'] for a in execute(
        "SELECT DISTINCT date FROM fitness_activities WHERE user_id=? AND date>=?",
        (uid, d30), fetchall=True)}
    on  = [h for d, h in sleep.items() if d in workout_days]
    off = [h for d, h in sleep.items() if d not in workout_days]
    if len(on) >= 4 and len(off) >= 4:
        diff = sum(on)/len(on) - sum(off)/len(off)
        if diff >= 0.4:
            add('🏃', f"You sleep {abs(round(diff*60))} min longer on workout days — exercise is earning its keep",
                'info')

    # 4. Water streak (consecutive days at goal, ending today or yesterday)
    rs = execute("SELECT water_goal_ml FROM reminder_settings WHERE user_id=?",
                 (uid,), fetchone=True)
    goal = (rs or {}).get('water_goal_ml') or 2450
    daily = {r['date_key']: r['total'] for r in execute(
        """SELECT date_key, SUM(amount_ml) AS total FROM hydration_logs
           WHERE user_id=? AND date_key>=? GROUP BY date_key""",
        (uid, (today - dt.timedelta(days=13)).isoformat()), fetchall=True)}
    streak, day = 0, today
    if daily.get(today.isoformat(), 0) < goal:
        day = today - dt.timedelta(days=1)   # today may still be in progress
    while daily.get(day.isoformat(), 0) >= goal:
        streak += 1
        day -= dt.timedelta(days=1)
    if streak >= 3:
        add('💧', f"{streak} days in a row at your water goal", 'success')

    # 5. Sleep trend: this week vs the three weeks before (≥4 nights each)
    this_week = [h for d, h in sleep.items() if d >= d7]
    earlier   = [h for d, h in sleep.items() if d < d7]
    if len(this_week) >= 4 and len(earlier) >= 4:
        cur, prev = sum(this_week)/len(this_week), sum(earlier)/len(earlier)
        if prev and abs(cur - prev) / prev >= 0.05:
            arrow, tone = ('up', 'success') if cur > prev else ('down', 'warning')
            add('🌙', f"Sleep is {arrow} {abs(round((cur-prev)/prev*100))}% this week "
                      f"({round(cur,1)}h vs {round(prev,1)}h average)", tone)

    # 6. Protein target hits (needs a complete profile)
    try:
        from .food import get_profile, calc_tdee
        target = (calc_tdee(get_profile()) or {}).get('protein_g')
        if target:
            rows = execute("""SELECT date_key, SUM(protein) AS p FROM food_logs
                              WHERE user_id=? AND date_key>=? GROUP BY date_key""",
                           (uid, d7), fetchall=True)
            hits = sum(1 for r in rows if (r['p'] or 0) >= target * 0.9)
            if len(rows) >= 4 and hits >= 4:
                add('💪', f"Protein target hit {hits} of the last {len(rows)} logged days", 'success')
    except Exception:
        pass

    # 7. Perfect logging week (something logged every one of the last 7 days)
    logged_days = set()
    for table, col in [('food_logs', 'date_key'), ('hydration_logs', 'date_key'),
                       ('sleep_logs', 'date_key'), ('thoughts', 'date_key'),
                       ('habit_logs', 'date_key')]:
        for r in execute(f"SELECT DISTINCT {col} AS d FROM {table} WHERE user_id=? AND {col}>=?",
                         (uid, d7), fetchall=True):
            logged_days.add(r['d'])
    if len(logged_days) >= 7:
        add('📈', 'Logged something every day this week — the data is working for you', 'success')

    return cards[:limit]


# ── Global search ─────────────────────────────────────────────────────────────

def _parse_date_query(query: str):
    """
    Parse natural language date references and return (clean_query, date_filter_sql, date_params).
    Handles: 'last week', 'last monday', 'last tuesday' etc., 'yesterday', 'today',
             'this month', 'last month', specific dates like 'june 3'.
    Returns (stripped_query, date_key_col_expr, [params]) or (query, None, []).
    """
    import datetime as dt, re
    today = dt.date.today()
    q = query.lower().strip()
    date_range = None

    # today / yesterday
    if re.search(r'\btoday\b', q):
        date_range = (today.isoformat(), today.isoformat())
        q = re.sub(r'\btoday\b', '', q).strip()
    elif re.search(r'\byesterday\b', q):
        d = today - dt.timedelta(days=1)
        date_range = (d.isoformat(), d.isoformat())
        q = re.sub(r'\byesterday\b', '', q).strip()

    # last week
    elif re.search(r'\blast week\b', q):
        start = today - dt.timedelta(days=today.weekday()+7)
        end   = start + dt.timedelta(days=6)
        date_range = (start.isoformat(), end.isoformat())
        q = re.sub(r'\blast week\b', '', q).strip()

    # this week
    elif re.search(r'\bthis week\b', q):
        start = today - dt.timedelta(days=today.weekday())
        date_range = (start.isoformat(), today.isoformat())
        q = re.sub(r'\bthis week\b', '', q).strip()

    # this month
    elif re.search(r'\bthis month\b', q):
        start = today.replace(day=1)
        date_range = (start.isoformat(), today.isoformat())
        q = re.sub(r'\bthis month\b', '', q).strip()

    # last month
    elif re.search(r'\blast month\b', q):
        first_this = today.replace(day=1)
        last_prev  = first_this - dt.timedelta(days=1)
        start = last_prev.replace(day=1)
        date_range = (start.isoformat(), last_prev.isoformat())
        q = re.sub(r'\blast month\b', '', q).strip()

    # last <weekday>  e.g. "last tuesday"
    else:
        days_map = {'monday':0,'tuesday':1,'wednesday':2,'thursday':3,
                    'friday':4,'saturday':5,'sunday':6}
        m = re.search(r'\blast (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', q)
        if m:
            target_wd = days_map[m.group(1)]
            delta = (today.weekday() - target_wd) % 7 or 7
            d = today - dt.timedelta(days=delta)
            date_range = (d.isoformat(), d.isoformat())
            q = re.sub(r'\blast ' + m.group(1) + r'\b', '', q).strip()

        # on <weekday>  e.g. "on monday"
        if not date_range:
            m = re.search(r'\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', q)
            if m:
                target_wd = days_map[m.group(1)]
                delta = (today.weekday() - target_wd) % 7
                d = today - dt.timedelta(days=delta)
                date_range = (d.isoformat(), d.isoformat())
                q = re.sub(r'\bon ' + m.group(1) + r'\b', '', q).strip()

    return q.strip() or None, date_range


def global_search(query: str, limit: int = 40) -> dict:
    uid = current_user_id()
    clean_q, date_range = _parse_date_query(query)
    # If entire query was a date phrase and nothing else, search everything in that range
    text_q = f'%{clean_q.lower()}%' if clean_q else '%'
    results = {'query': query, 'total': 0, 'sections': [], 'date_range': date_range}

    def date_filter(col):
        if not date_range: return '', []
        return f' AND {col} BETWEEN ? AND ?', list(date_range)

    # ── Food logs ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT food_name,date_key,calories,meal_type,quantity_g FROM food_logs"
        f" WHERE (LOWER(food_name) LIKE ? OR LOWER(meal_type) LIKE ?){df} AND user_id=?"
        f" ORDER BY date_key DESC LIMIT {limit//4}",
        [text_q, text_q] + dp + [uid], fetchall=True)
    if rows:
        results['sections'].append({'type':'food','label':'Food Logs','icon':'🍽️',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Thoughts ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT id,content,mood,date_key,created_at FROM thoughts"
        f" WHERE LOWER(content) LIKE ?{df} AND user_id=?"
        f" ORDER BY created_at DESC LIMIT {limit//5}",
        [text_q] + dp + [uid], fetchall=True)
    if rows:
        results['sections'].append({'type':'thought','label':'Thoughts','icon':'💭',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Symptoms ──
    df, dp = date_filter('date_key')
    rows = execute(
        f"SELECT id,name,severity,date_key,time_of_day,notes FROM symptoms"
        f" WHERE (LOWER(name) LIKE ? OR LOWER(notes) LIKE ?){df} AND user_id=?"
        f" ORDER BY date_key DESC LIMIT {limit//5}",
        [text_q, text_q] + dp + [uid], fetchall=True)
    if rows:
        results['sections'].append({'type':'symptom','label':'Symptoms','icon':'🩺',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Todos ──
    df, dp = date_filter('created_at')
    rows = execute(
        f"SELECT id,title,notes,status,priority,due_date,created_at FROM todos"
        f" WHERE (LOWER(title) LIKE ? OR LOWER(notes) LIKE ?){df} AND user_id=?"
        f" ORDER BY created_at DESC LIMIT {limit//5}",
        [text_q, text_q] + dp + [uid], fetchall=True)
    if rows:
        results['sections'].append({'type':'todo','label':'Tasks','icon':'✅',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Activities ──
    df, dp = date_filter('date')
    rows = execute(
        f"SELECT id,name,type,date,duration,calories,distance FROM fitness_activities"
        f" WHERE (LOWER(name) LIKE ? OR LOWER(type) LIKE ?){df} AND user_id=?"
        f" ORDER BY date DESC LIMIT {limit//5}",
        [text_q, text_q] + dp + [uid], fetchall=True)
    if rows:
        results['sections'].append({'type':'activity','label':'Workouts','icon':'🏃',
                                    'items':[dict(r) for r in rows]})
        results['total'] += len(rows)

    # ── Medicines ──
    if clean_q:
        rows = execute(
            "SELECT id,name,dosage,unit,frequency FROM medicines"
            " WHERE LOWER(name) LIKE ? AND active=1 AND user_id=? ORDER BY name LIMIT 5",
            (text_q, uid), fetchall=True)
        if rows:
            results['sections'].append({'type':'medicine','label':'Medicines','icon':'💊',
                                        'items':[dict(r) for r in rows]})
            results['total'] += len(rows)

    # ── Reports ──
    df, dp = date_filter('report_date')
    rows = execute(
        f"SELECT id,filename,patient_name,doctor,severity,report_date FROM reports"
        f" WHERE (LOWER(filename) LIKE ? OR LOWER(patient_name) LIKE ? OR LOWER(doctor) LIKE ?){df} AND user_id=?"
        f" ORDER BY report_date DESC LIMIT 5",
        [text_q, text_q, text_q] + dp + [uid], fetchall=True)
    if rows:
        items = [{'id':r['id'],'filename':r['filename'],'patient':r['patient_name'],
                  'doctor':r['doctor'],'severity':r['severity'],'date':r['report_date']} for r in rows]
        results['sections'].append({'type':'report','label':'Medical Reports','icon':'📋','items':items})
        results['total'] += len(rows)

    return results

# ── Goal progress data ────────────────────────────────────────────────────────

def get_goal_progress() -> dict:
    import datetime as dt
    uid = current_user_id()
    today = dt.date.today()
    month_start = today.replace(day=1).isoformat()
    week_start  = (today - dt.timedelta(days=6)).isoformat()
    days30_start = (today - dt.timedelta(days=29)).isoformat()

    profile = get_profile()
    targets = calc_tdee(profile)

    # Weight trend (all entries, up to 60 days for chart)
    bm_rows = execute(
        "SELECT date_key,weight_kg,bmi FROM body_metrics WHERE weight_kg IS NOT NULL AND user_id=? ORDER BY date_key",
        (uid,), fetchall=True)
    weight_trend = [{'date':r['date_key'],'weight':r['weight_kg'],'bmi':r['bmi']} for r in bm_rows[-60:]]

    # Workout frequency this month + daily workout presence for chart
    acts_month = execute("SELECT date FROM fitness_activities WHERE date >= ? AND user_id=?",
                         (month_start, uid), fetchall=True)
    workout_days_month = len(set(r['date'] for r in acts_month))
    days_in_month = today.day

    # 30-day daily workout map for mini bar chart
    acts_30 = execute("SELECT date, SUM(calories) as cal FROM fitness_activities WHERE date >= ? AND user_id=? GROUP BY date",
                      (days30_start, uid), fetchall=True)
    workout_map = {r['date']: r['cal'] for r in acts_30}
    daily_workouts = []
    for i in range(29, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily_workouts.append({'date': d, 'cal': workout_map.get(d, 0)})

    # Habit completion this month + per-habit breakdown. Count completions
    # WITHIN this month, to match the days-elapsed denominator — summing the full
    # 30-day done_dates over today.day (4 on the 4th) gave 8 ÷ 4 = 200%. This now
    # matches the per-habit done_this_month below.
    # Fetch at least days-elapsed-this-month, not a flat 30 — on the 31st a
    # 30-day window starts on the 2nd and can never include the 1st, understating
    # a perfect month as 30/31 = 96.8%.
    habit_stats = get_habit_stats(max(30, days_in_month))
    total_habits = len(habit_stats['habits'])
    habit_done = sum(sum(1 for d in h['done_dates'] if d >= month_start) for h in habit_stats['habits'])
    habit_possible = total_habits * days_in_month
    habit_pct = min(round(habit_done / habit_possible * 100, 1), 100) if habit_possible else 0
    # Per-habit detail
    habit_detail = []
    for h in habit_stats['habits'][:6]:
        done_this_month = sum(1 for d in h['done_dates'] if d >= month_start)
        pct = round(done_this_month / days_in_month * 100)
        habit_detail.append({'name': h['name'], 'emoji': h['emoji'], 'color': h['color'],
                              'streak': h['streak'], 'pct': pct, 'done': done_this_month})

    # Sleep — 30 days of data
    sleep_rows = execute(
        "SELECT date_key,duration_h,quality FROM sleep_logs WHERE date_key >= ? AND user_id=? ORDER BY date_key",
        (days30_start, uid), fetchall=True)
    sleep_list = [{'date':r['date_key'],'h':r['duration_h'],'q':r['quality']} for r in sleep_rows]
    sleep_7 = [r for r in sleep_list if r['date'] >= week_start]
    avg_sleep_7 = round(sum(r['h'] for r in sleep_7)/len(sleep_7),1) if sleep_7 else None
    avg_sleep_30 = round(sum(r['h'] for r in sleep_list)/len(sleep_list),1) if sleep_list else None

    # Calorie adherence — 30 days
    food_rows = execute(
        "SELECT date_key, SUM(calories) as total FROM food_logs WHERE date_key >= ? AND user_id=? GROUP BY date_key",
        (days30_start, uid), fetchall=True)
    food_map = {r['date_key']: round(r['total'] or 0) for r in food_rows}
    daily_cals = []
    for i in range(29, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        daily_cals.append({'date': d, 'cal': food_map.get(d, 0)})
    cal_this_week = sum(food_map.get((today - dt.timedelta(days=i)).isoformat(), 0) for i in range(7))
    # target_calories is None until the profile has weight/height/age/gender
    cal_target_week = targets['target_calories'] * 7 if targets['target_calories'] else None
    cal_adherence = round(cal_this_week / cal_target_week * 100, 1) if cal_target_week else 0

    return {
        'profile': profile, 'targets': targets,
        'weight_trend': weight_trend,
        'workouts': {
            'this_month': workout_days_month, 'days_elapsed': days_in_month,
            # Rolling 30-day window, not days-elapsed-this-month: with
            # `today.day` as the denominator a single workout read 100% on the
            # 1st and 50% on the 2nd, which is noise rendered with the
            # authority of a statistic. A fixed window means the same thing
            # every day of the month.
            'frequency_pct': round(len(workout_map) / 30 * 100),
            'daily': daily_workouts
        },
        'habits': {
            'total': total_habits, 'completion_pct': habit_pct,
            'done_count': habit_done, 'detail': habit_detail
        },
        'sleep': {
            'avg_7': avg_sleep_7, 'avg_30': avg_sleep_30,
            'target_hours': 7.5, 'logged_30': len(sleep_list),
            'daily': sleep_list
        },
        'nutrition': {
            'cal_this_week': cal_this_week, 'cal_target': cal_target_week,
            'adherence_pct': cal_adherence, 'daily': daily_cals,
            'target_daily': targets['target_calories']
        },
        'refill_alerts': get_low_stock_medicines(),
    }
