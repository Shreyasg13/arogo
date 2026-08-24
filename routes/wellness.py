"""routes/wellness.py — Hydration, sleep, body metrics, thoughts, todos,
   habits, symptoms, vitals, emergency, medicine stock, notifications."""
from db.food import get_user_timezone
from flask import Blueprint, request, jsonify
from auth import require_auth
from db import *

bp = Blueprint("wellness", __name__)

# ── Medicine stock ────────────────────────────────────────────────────────────
@bp.route('/api/medicines/<mid>/stock', methods=['POST'])
@require_auth
def api_update_stock(mid):
    d = request.json or {}
    note = d.get('pharmacy_note')
    m = update_medicine_stock(mid, to_int(d.get('pill_count', 0), 0, lo=0, hi=100000),
                              to_int(d.get('pills_per_dose', 1), 1, lo=1, hi=100),
                              to_int(d.get('refill_threshold', 7), 7, lo=0, hi=365),
                              pharmacy_note=note if isinstance(note, str) else None)
    return jsonify({'success': True, 'medicine': m})

@bp.route('/api/medicines/<mid>/refill/ordered', methods=['POST'])
@require_auth
def api_refill_ordered(mid):
    return jsonify({'success': True, 'medicine': mark_refill_ordered(mid)})

@bp.route('/api/medicines/<mid>/refill/note', methods=['POST'])
@require_auth
def api_refill_note(mid):
    note = (request.json or {}).get('pharmacy_note', '')
    return jsonify({'success': True, 'medicine': set_pharmacy_note(mid, note)})

@bp.route('/api/medicines/low-stock')
@require_auth
def api_low_stock():
    return jsonify(get_low_stock_medicines())

# ── Appointments ────────────────────────────────────────────────────────────
@bp.route('/api/appointments')
@require_auth
def api_list_appointments():
    upcoming = request.args.get('upcoming') in ('1', 'true', 'yes')
    return jsonify({'appointments': list_appointments(upcoming_only=upcoming),
                    'next': get_next_appointment()})

@bp.route('/api/appointments', methods=['POST'])
@require_auth
def api_add_appointment():
    try:
        return jsonify({'success': True, 'appointment': create_appointment(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/appointments/<aid>', methods=['PATCH'])
@require_auth
def api_update_appointment(aid):
    from db.health import update_appointment
    try:
        return jsonify({'success': True, 'appointment': update_appointment(aid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/appointments/<aid>', methods=['DELETE'])
@require_auth
def api_delete_appointment(aid):
    delete_appointment(aid)
    return jsonify({'success': True})

# ── Doctor-visit prep questions ──────────────────────────────────────────────
@bp.route('/api/doctor-questions')
@require_auth
def api_list_doctor_questions():
    return jsonify({'questions': list_doctor_questions()})

@bp.route('/api/doctor-questions', methods=['POST'])
@require_auth
def api_add_doctor_question():
    try:
        return jsonify({'success': True, 'question': add_doctor_question((request.json or {}).get('question', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/doctor-questions/<qid>/toggle', methods=['POST'])
@require_auth
def api_toggle_doctor_question(qid):
    toggle_doctor_question(qid)
    return jsonify({'success': True})

@bp.route('/api/doctor-questions/<qid>', methods=['DELETE'])
@require_auth
def api_delete_doctor_question(qid):
    delete_doctor_question(qid)
    return jsonify({'success': True})

# ── Per-appointment visit flow (before / during / after in one place) ────────
@bp.route('/api/appointments/<aid>/detail')
@require_auth
def api_visit_detail(aid):
    from db.visit_flow import get_visit_detail
    d = get_visit_detail(aid)
    if d is None:
        return jsonify({'error': 'Appointment not found'}), 404
    return jsonify(d)

@bp.route('/api/appointments/<aid>/questions', methods=['POST'])
@require_auth
def api_add_visit_question(aid):
    try:
        q = add_doctor_question((request.json or {}).get('question', ''), appointment_id=aid)
        return jsonify({'success': True, 'question': q})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/appointments/<aid>/actions', methods=['POST'])
@require_auth
def api_add_visit_action(aid):
    from db.visit_flow import add_visit_action
    try:
        return jsonify({'success': True, 'action': add_visit_action(aid, (request.json or {}).get('text', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/visit-actions/<iid>/toggle', methods=['POST'])
@require_auth
def api_toggle_visit_action(iid):
    from db.visit_flow import toggle_visit_action
    toggle_visit_action(iid)
    return jsonify({'success': True})

@bp.route('/api/visit-actions/<iid>', methods=['DELETE'])
@require_auth
def api_delete_visit_action(iid):
    from db.visit_flow import delete_visit_action
    delete_visit_action(iid)
    return jsonify({'success': True})

# ── Measurement reminders ───────────────────────────────────────────────────
@bp.route('/api/measurement-reminders')
@require_auth
def api_list_measurement_reminders():
    return jsonify({'reminders': list_measurement_reminders()})

@bp.route('/api/measurement-reminders', methods=['POST'])
@require_auth
def api_add_measurement_reminder():
    d = request.json or {}
    try:
        return jsonify({'success': True,
                        'reminder': add_measurement_reminder(d.get('kind', ''), d.get('time', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/measurement-reminders/<rid>/toggle', methods=['POST'])
@require_auth
def api_toggle_measurement_reminder(rid):
    return jsonify({'success': True, 'reminder': toggle_measurement_reminder(rid)})

@bp.route('/api/measurement-reminders/<rid>', methods=['DELETE'])
@require_auth
def api_delete_measurement_reminder(rid):
    delete_measurement_reminder(rid)
    return jsonify({'success': True})

# NOTE: GET /api/medicines/adherence lives in routes/medicines.py (registered
# first, so it owns the URL — it returns adherence stats). This duplicate
# returned a different shape ({medicines: [...]}) and was dead code; removed.

@bp.route('/api/medicines/streaks')
@require_auth
def api_medicine_streaks():
    """
    Per-medicine streak + adherence data for the last 30 days.
    Returns streak, best streak, 30-day dot grid, overall adherence %.
    """
    import datetime as dt
    from db.medicines import list_medicines
    from db.core import execute

    days     = to_int(request.args.get('days', 30), 30, lo=0, hi=3650)
    today    = dt.date.today()
    meds     = [m for m in list_medicines() if m['active']]

    # Date range: oldest first (empty when days=0)
    date_range = [(today - dt.timedelta(days=i)).isoformat()
                  for i in range(days - 1, -1, -1)]
    range_start = date_range[0] if date_range else today.isoformat()

    overall_total = 0
    overall_taken = 0
    results = []

    for m in meds:
        times    = m.get('times', []) or ['08:00']
        mid      = m['id']
        expected = len(times)   # doses expected per day

        # Fetch all dose_logs for this medicine in range
        from db.core import current_user_id
        logs = execute(
            """SELECT date_key, time_key, taken FROM dose_logs
               WHERE medicine_id=? AND date_key >= ? AND user_id=? ORDER BY date_key""",
            (mid, range_start, current_user_id()), fetchall=True)
        log_lookup = {}
        for lg in logs:
            log_lookup[(lg['date_key'], lg['time_key'])] = bool(lg['taken'])

        # Per-day adherence — oldest first pass
        day_data = []
        all_taken = 0
        all_total = 0
        best_streak = 0
        run = 0

        for date_key in date_range:
            day_taken = sum(
                1 for t in times
                if log_lookup.get((date_key, t), False)
            )
            day_total     = expected
            day_pct       = round(day_taken / day_total * 100) if day_total else 0
            all_taken    += day_taken
            all_total    += day_total
            overall_taken += day_taken
            overall_total += day_total
            full_day = day_taken == day_total and day_total > 0

            if full_day:
                run += 1
                best_streak = max(best_streak, run)
            else:
                run = 0

            day_data.append({
                'date':  date_key,
                'taken': day_taken,
                'total': day_total,
                'pct':   day_pct,
                'full':  full_day,
            })

        # Streak = fully-taken days counting BACK from today, but a single
        # missed day is forgiven (grace) rather than resetting to zero. A
        # forgiven day is NOT counted as taken — streak is real full days only.
        from streaks import forgiving_streak
        full_days = {d['date'] for d in day_data if d['full']}
        earliest = dt.date.fromisoformat(range_start) if date_range else today
        _st = forgiving_streak(full_days, today=today, grace=1, earliest=earliest)
        streak = _st['streak']
        streak_grace_used = _st['grace_used']

        adh_pct = round(all_taken / all_total * 100, 1) if all_total else 0

        results.append({
            'id':          mid,
            'name':        m['name'],
            'dosage':      m.get('dosage', ''),
            'unit':        m.get('unit', ''),
            'icon':        m.get('icon', '💊'),
            'color':       m.get('color', 'teal'),
            'frequency':   m.get('frequency', 'once_daily'),
            'times':       times,
            'streak':      streak,
            'grace_used':  streak_grace_used,
            'best_streak': best_streak,
            'adherence_pct': adh_pct,
            'taken_total': all_taken,
            'days':        day_data,
        })

    # Sort by streak desc, then adherence
    results.sort(key=lambda x: (x['streak'], x['adherence_pct']), reverse=True)

    overall_pct = round(overall_taken / overall_total * 100, 1) if overall_total else 0

    return jsonify({
        'medicines':      results,
        'overall_pct':    overall_pct,
        'overall_taken':  overall_taken,
        'overall_total':  overall_total,
        'days':           days,
        'date_range':     date_range,
    })



# ── Hydration ─────────────────────────────────────────────────────────────────
@bp.route('/api/hydration/<date_key>')
@require_auth
def api_hydration_day(date_key):
    return jsonify(get_hydration_day(date_key))

@bp.route('/api/hydration/week')
@require_auth
def api_hydration_week():
    return jsonify(get_hydration_week())

# Water logged by tapping the reminder's button is marked, because it isn't
# evidence of anything the user chose. The button's amount comes FROM
# usual_sip_ml, so counting the tap as a deliberate choice feeds our own number
# back in as if it were theirs — see usual_sip_ml for the loop this closes.
HYDRATION_SOURCE_NOTIF = 'notif'


@bp.route('/api/hydration', methods=['POST'])
@require_auth
def api_log_hydration():
    d = request.json or {}
    # A garbage date_key would orphan the log on a day the UI can't navigate
    # to, where it counts toward no total and can't be deleted. The food route
    # already rejects this; hydration was the gap.
    date_key = d.get('date_key') or today_iso(get_user_timezone())
    if not valid_date(date_key):
        return jsonify({'success': False, 'error': 'Invalid date'}), 400
    # Only this one literal is honoured — the client can't set arbitrary
    # provenance (source_id also links food-log credits, which it must not forge).
    source = HYDRATION_SOURCE_NOTIF if d.get('source') == 'notification' else None
    log_hydration(d.get('amount_ml', 250), d.get('drink_type', 'water'), date_key,
                  source_id=source, idem_key=d.get('idem_key'))
    return jsonify({'success': True})

@bp.route('/api/hydration/<lid>', methods=['DELETE'])
@require_auth
def api_del_hydration(lid):
    delete_hydration_log(lid)
    return jsonify({'success': True})

# ── Sleep ─────────────────────────────────────────────────────────────────────
@bp.route('/api/sleep')
@require_auth
def api_sleep():
    days = int(request.args.get('days', 14))
    return jsonify(get_sleep_logs(days))

@bp.route('/api/sleep', methods=['POST'])
@require_auth
def api_log_sleep():
    s = log_sleep(request.json or {})
    return jsonify({'success': True, 'log': s})

@bp.route('/api/sleep/<lid>', methods=['DELETE'])
@require_auth
def api_del_sleep(lid):
    delete_sleep_log(lid)
    return jsonify({'success': True})

@bp.route('/api/sleep/insights')
@require_auth
def api_sleep_insights():
    days = int(request.args.get('days', 14))
    return jsonify(get_sleep_insights(days))

@bp.route('/api/sleep/target', methods=['GET', 'POST'])
@require_auth
def api_sleep_target():
    if request.method == 'POST':
        try:
            h = set_sleep_target((request.json or {}).get('hours'))
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        return jsonify({'success': True, 'target_h': h})
    return jsonify({'target_h': get_sleep_target()})

@bp.route('/api/sleep/trend')
@require_auth
def api_sleep_trend():
    """Return 30-day sleep stats shaped for charting."""
    import datetime as dt

    days  = int(request.args.get('days', 30))
    rows  = get_sleep_logs(days=days)

    if not rows:
        return jsonify({'days': days, 'logs': [], 'stats': {}, 'weekly': []})

    sorted_rows = sorted(rows, key=lambda x: x['date_key'])

    durations  = [r['duration_h'] for r in sorted_rows]
    qualities  = [r['quality']    for r in sorted_rows]

    # Overall stats
    avg_dur  = round(sum(durations) / len(durations), 1)
    best_dur = round(max(durations), 1)
    avg_qual = round(sum(qualities) / len(qualities), 1)

    # Duration trend — only once there's a week's worth of nights, and only for
    # a shift big enough to mean something. Calling sleep "worsening" off two or
    # three nights (really off a single short night) reads as an alarm the data
    # can't support. Below the threshold we don't classify at all.
    TREND_MIN_NIGHTS = 7
    TREND_DELTA_H    = 0.5           # 30 min; smaller swings are night-to-night noise
    if len(durations) >= TREND_MIN_NIGHTS:
        mid        = len(durations) // 2
        first_avg  = sum(durations[:mid]) / mid
        second_avg = sum(durations[mid:]) / (len(durations) - mid)
        if second_avg - first_avg > TREND_DELTA_H:
            dur_trend = 'improving'
        elif first_avg - second_avg > TREND_DELTA_H:
            dur_trend = 'worsening'
        else:
            dur_trend = 'stable'
    else:
        dur_trend = 'insufficient'   # not enough nights to say anything yet

    # Days with 7h+ (recommended)
    good_nights = sum(1 for d in durations if d >= 7)

    # Bed/wake-time consistency — how much the clock times drift, stated
    # neutrally (a regular schedule is easier on the body, but we don't grade it).
    # Bedtimes are shifted across midnight so 11pm and 12:30am cluster instead of
    # sitting a whole day apart.
    def _tmin(hhmm, shift_early=False):
        try:
            h, m = int(hhmm[:2]), int(hhmm[3:5])
        except (ValueError, TypeError, IndexError):
            return None
        v = h * 60 + m
        if shift_early and h < 12:
            v += 1440
        return v

    def _mean_std(vals):
        vals = [v for v in vals if v is not None]
        if len(vals) < 3:
            return None, None
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        return mean, std

    def _fmt_min(m):
        if m is None:
            return None
        m = int(round(m)) % 1440
        return f"{m // 60:02d}:{m % 60:02d}"

    bed_mean, bed_std   = _mean_std([_tmin(r['bedtime'], shift_early=True) for r in sorted_rows])
    wake_mean, wake_std = _mean_std([_tmin(r['wake_time']) for r in sorted_rows])

    # Week-over-week breakdown (last 4 weeks)
    today = dt.date.today()
    weekly = []
    for week_back in range(3, -1, -1):
        wstart = today - dt.timedelta(days=(week_back + 1) * 7)
        wend   = today - dt.timedelta(days=week_back * 7)
        wrows  = [r for r in sorted_rows
                  if wstart.isoformat() <= r['date_key'] < wend.isoformat()]
        if wrows:
            wdurs = [r['duration_h'] for r in wrows]
            weekly.append({
                'label':    f'W{4 - week_back}',
                'avg_dur':  round(sum(wdurs) / len(wdurs), 1),
                'nights':   len(wrows),
                'good':     sum(1 for d in wdurs if d >= 7),
            })

    return jsonify({
        'days':  days,
        'total': len(rows),
        'logs':  sorted_rows,
        'stats': {
            'avg_duration':  avg_dur,
            'best_night':    best_dur,
            'avg_quality':   avg_qual,
            'good_nights':   good_nights,
            'good_pct':      round(good_nights / len(rows) * 100),
            'dur_trend':     dur_trend,
            'logged_nights': len(rows),
            'avg_bedtime':      _fmt_min(bed_mean),
            'avg_waketime':     _fmt_min(wake_mean),
            'bedtime_spread':   None if bed_std  is None else int(round(bed_std)),
            'waketime_spread':  None if wake_std is None else int(round(wake_std)),
        },
        'weekly': weekly,
    })



# ── Body metrics ──────────────────────────────────────────────────────────────
@bp.route('/api/body-metrics')
@require_auth
def api_body_metrics():
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=3650)
    return jsonify(get_body_metrics(days))

@bp.route('/api/body-metrics/measurements')
@require_auth
def api_measurement_trends():
    days = int(request.args.get('days', 180))
    return jsonify(get_measurement_trends(days))

@bp.route('/api/body-metrics', methods=['POST'])
@require_auth
def api_log_body():
    try:
        m = log_body_metric(request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'metric': m})


# ── Cycle / period tracking ──────────────────────────────────────────────────
@bp.route('/api/cycle')
@require_auth
def api_cycle():
    return jsonify(get_cycle_summary())

@bp.route('/api/cycle/start', methods=['POST'])
@require_auth
def api_cycle_start():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'summary': log_period_start(d.get('start_date', ''), d.get('notes', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/cycle/end', methods=['POST'])
@require_auth
def api_cycle_end():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'summary': log_period_end(d.get('end_date', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/cycle/<cid>', methods=['DELETE'])
@require_auth
def api_cycle_delete(cid):
    return jsonify({'success': True, 'summary': delete_cycle(cid)})

@bp.route('/api/cycle/symptoms/<date_key>')
@require_auth
def api_cycle_symptoms_get(date_key):
    return jsonify(get_symptom_day(date_key))

@bp.route('/api/cycle/symptoms', methods=['POST'])
@require_auth
def api_cycle_symptoms_save():
    d = request.json or {}
    try:
        day = log_symptoms(d.get('date_key', ''), d.get('symptoms'),
                           d.get('flow'), d.get('notes', ''))
        return jsonify({'success': True, 'day': day, 'summary': get_symptom_summary()})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@bp.route('/api/cycle/symptoms')
@require_auth
def api_cycle_symptoms_summary():
    return jsonify(get_symptom_summary())
@bp.route('/api/body-metrics/trend')
@require_auth
def api_body_metrics_trend():
    """All-time weight data + goal projection line."""
    import datetime as dt
    from db.core import execute
    from db.food import get_profile, calc_tdee

    days   = int(request.args.get('days', 365))
    start  = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    from db.core import current_user_id
    rows   = execute(
        "SELECT date_key, weight_kg, body_fat_pct, bmi FROM body_metrics "
        "WHERE weight_kg IS NOT NULL AND date_key >= ? AND user_id=? ORDER BY date_key",
        (start, current_user_id()), fetchall=True)
    logs   = [dict(r) for r in rows]

    profile = get_profile()
    targets = calc_tdee(profile)

    start_weight  = logs[0]['weight_kg']  if logs else None
    latest_weight = logs[-1]['weight_kg'] if logs else None
    target_weight = profile.get('target_weight_kg')
    goal          = profile.get('goal', 'maintain')
    current_weight = to_num(profile.get('weight_kg'), 70)

    # ── Goal projection ───────────────────────────────────────────
    # Rate of change from calorie deficit/surplus
    # 500 kcal/day deficit ≈ 0.5 kg/week (7700 kcal per kg fat)
    GOAL_RATE_KG_WEEK = {
        'lose_fast': -0.5, 'lose': -0.25,
        'maintain':  0,
        'gain':       0.25, 'gain_fast': 0.5,
    }
    rate_per_week = GOAL_RATE_KG_WEEK.get(goal, 0)

    projection = []
    if target_weight and rate_per_week != 0 and logs:
        anchor_date   = dt.date.fromisoformat(logs[-1]['date_key'])
        anchor_weight = logs[-1]['weight_kg']
        weeks_needed  = (target_weight - anchor_weight) / rate_per_week if rate_per_week != 0 else 0
        # Only project if direction matches goal
        if (rate_per_week < 0 and target_weight < anchor_weight) or            (rate_per_week > 0 and target_weight > anchor_weight):
            weeks_needed = abs(weeks_needed)
            for week in range(int(weeks_needed) + 2):
                proj_date   = anchor_date + dt.timedelta(weeks=week)
                proj_weight = round(anchor_weight + rate_per_week * week, 2)
                # Clamp at target
                if rate_per_week < 0:
                    proj_weight = max(proj_weight, target_weight)
                else:
                    proj_weight = min(proj_weight, target_weight)
                projection.append({'date': proj_date.isoformat(), 'weight': proj_weight})

    # ── Stats ─────────────────────────────────────────────────────
    total_change  = round(latest_weight - start_weight, 2) if (start_weight and latest_weight) else 0
    pct_to_goal   = None
    if target_weight and start_weight and latest_weight and start_weight != target_weight:
        pct_to_goal = min(100, round(
            abs(latest_weight - start_weight) / abs(target_weight - start_weight) * 100, 1
        ))

    # Estimated arrival date (from the PLAN's assumed rate)
    eta_date = None
    if projection:
        last_proj = projection[-1]
        if abs(last_proj['weight'] - target_weight) < 0.1:
            eta_date = last_proj['date']

    # ── Measured pace + ETA from ACTUAL weigh-ins ─────────────────
    # rate_per_week/eta_date above come from the goal SETTING (an assumed rate),
    # not from what the scale actually shows. These reflect the real trend, so
    # the UI can show "at your current pace" honestly instead of "if you follow
    # the plan". Needs at least a week between the first and last weigh-in.
    measured_rate = None
    measured_eta  = None
    on_track      = None
    if len(logs) >= 2 and start_weight and latest_weight:
        d0 = dt.date.fromisoformat(logs[0]['date_key'])
        d1 = dt.date.fromisoformat(logs[-1]['date_key'])
        span_days = (d1 - d0).days
        if span_days >= 7:
            measured_rate = round((latest_weight - start_weight) / (span_days / 7), 2)
            if target_weight is not None:
                remaining = target_weight - latest_weight
                if abs(remaining) < 0.1:
                    on_track, measured_eta = True, d1.isoformat()   # already there
                elif measured_rate != 0 and (
                        (remaining < 0 and measured_rate < 0) or
                        (remaining > 0 and measured_rate > 0)):
                    on_track = True                                 # moving toward goal
                    weeks_to = remaining / measured_rate
                    measured_eta = (d1 + dt.timedelta(weeks=weeks_to)).isoformat()
                else:
                    on_track = False    # flat or moving away — no honest ETA

    return jsonify({
        'logs':           logs,
        'projection':     projection,
        'profile':        profile,
        'targets':        targets,
        'stats': {
            'start_weight':   start_weight,
            'latest_weight':  latest_weight,
            'current_weight': current_weight,
            'target_weight':  target_weight,
            'total_change':   total_change,
            'pct_to_goal':    pct_to_goal,
            'goal':           goal,
            'rate_per_week':  rate_per_week,
            'eta_date':       eta_date,
            'measured_rate_per_week': measured_rate,
            'measured_eta_date':      measured_eta,
            'on_track':               on_track,
            'logged_entries': len(logs),
        },
    })



# ── Thoughts / Journal ────────────────────────────────────────────────────────
@bp.route('/api/thoughts/<date_key>')
@require_auth
def api_get_thoughts(date_key):
    # Rich shape the journal UI expects: {thoughts, count, remaining, limit, date}.
    # (A bare list here silently emptied the feed and broke the daily quota.)
    from db.wellness import MAX_THOUGHTS_PER_DAY
    thoughts = get_thoughts(date_key)
    count = len(thoughts)
    return jsonify({
        'thoughts':  thoughts,
        'count':     count,
        'remaining': max(0, MAX_THOUGHTS_PER_DAY - count),
        'limit':     MAX_THOUGHTS_PER_DAY,
        'date':      date_key,
    })

@bp.route('/api/thoughts', methods=['POST'])
@require_auth
def api_save_thought():
    d = request.json or {}
    try:
        t = save_thought(d.get('content',''), d.get('mood','neutral'),
                         d.get('date_key', today_iso(get_user_timezone())),
                         triggers=d.get('triggers'), idem_key=d.get('idem_key'))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'thought': t})

@bp.route('/api/thoughts/<tid>', methods=['PUT'])
@require_auth
def api_update_thought(tid):
    d = request.json or {}
    t = update_thought(tid, d.get('content',''), d.get('mood','neutral'),
                       triggers=d.get('triggers'))
    return jsonify({'success': True, 'thought': t})

@bp.route('/api/thoughts/patterns')
@require_auth
def api_thought_patterns():
    """Which triggers show up most on low-mood days (honest, non-causal)."""
    from db.wellness import get_trigger_patterns
    return jsonify(get_trigger_patterns())

@bp.route('/api/thoughts/<tid>', methods=['DELETE'])
@require_auth
def api_del_thought(tid):
    delete_thought(tid)
    return jsonify({'success': True})

@bp.route('/api/thoughts')
@require_auth
def api_thoughts_list():
    return jsonify(get_thoughts_range(30))

# ── Todos ─────────────────────────────────────────────────────────────────────
@bp.route('/api/todos')
@require_auth
def api_todos():
    return jsonify({'todos': list_todos()})

@bp.route('/api/todos', methods=['POST'])
@require_auth
def api_create_todo():
    try:
        t = create_todo(request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'todo': t})

@bp.route('/api/todos/<tid>', methods=['PUT'])
@require_auth
def api_update_todo(tid):
    try:
        t = update_todo(tid, request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'todo': t})

@bp.route('/api/todos/<tid>', methods=['DELETE'])
@require_auth
def api_del_todo(tid):
    delete_todo(tid)
    return jsonify({'success': True})

@bp.route('/api/todos/<tid>/toggle', methods=['POST'])
@require_auth
def api_toggle_todo(tid):
    toggle_todo(tid)
    return jsonify({'success': True})

@bp.route('/api/todos/reminders/due')
@require_auth
def api_due_reminders():
    return jsonify(get_due_reminders())

# ── Habits ────────────────────────────────────────────────────────────────────
@bp.route('/api/habits')
@require_auth
def api_habits():
    return jsonify(get_habit_stats())

@bp.route('/api/habits', methods=['POST'])
@require_auth
def api_create_habit():
    try:
        h = create_habit(request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'habit': h})

@bp.route('/api/habits/<hid>', methods=['DELETE'])
@require_auth
def api_del_habit(hid):
    delete_habit(hid)
    return jsonify({'success': True})

@bp.route('/api/habits/<hid>/toggle', methods=['POST'])
@require_auth
def api_toggle_habit(hid):
    d = request.json or {}
    result = toggle_habit_log(hid, d.get('date_key', today_iso(get_user_timezone())))
    return jsonify({'success': True, **result})

# ── Symptoms ──────────────────────────────────────────────────────────────────
@bp.route('/api/symptoms')
@require_auth
def api_symptoms():
    days = to_int(request.args.get('days', 14), 14, lo=1, hi=3650)
    return jsonify(get_symptoms(days))

@bp.route('/api/symptoms/timeline')
@require_auth
def api_symptom_timeline():
    """Symptoms overlaid against medicine start dates — coincidence, not cause."""
    days = to_int(request.args.get('days', 90), 90, lo=7, hi=365)
    return jsonify(get_symptom_med_timeline(days))

@bp.route('/api/symptoms/by-region')
@require_auth
def api_symptoms_by_region():
    """Symptom counts per body region for the body-map (I7)."""
    days = to_int(request.args.get('days', 90), 90, lo=1, hi=3650)
    return jsonify(get_symptoms_by_region(days))

@bp.route('/api/symptoms', methods=['POST'])
@require_auth
def api_log_symptom():
    try:
        s = log_symptom(request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'symptom': s})

@bp.route('/api/symptoms/<sid>', methods=['DELETE'])
@require_auth
def api_del_symptom(sid):
    delete_symptom(sid)
    return jsonify({'success': True})
@bp.route('/api/symptoms/patterns')
@require_auth
def api_symptom_patterns():
    """
    Analyse 30 days of symptom logs and return:
    - per-symptom frequency, severity trend, time-of-day pattern
    - active alerts (symptoms appearing 3+ times in last 7 days)
    - co-occurrence pairs (symptoms logged on same day)
    """
    import datetime as dt
    from collections import defaultdict, Counter

    days    = int(request.args.get('days', 30))
    rows    = get_symptoms(days=days)
    today   = dt.date.today()
    week_ago = (today - dt.timedelta(days=7)).isoformat()

    # ── per-symptom stats ────────────────────────────────────────
    by_name = defaultdict(list)
    for r in rows:
        by_name[r['name']].append(r)

    symptoms = []
    for name, entries in by_name.items():
        sorted_entries  = sorted(entries, key=lambda x: x['date_key'])
        recent          = [e for e in entries if e['date_key'] >= week_ago]
        severities      = [e['severity'] for e in sorted_entries]
        times           = Counter(e['time_of_day'] for e in entries)
        peak_time       = times.most_common(1)[0][0] if times else 'morning'

        # Severity trend — only once a symptom's been logged enough times to
        # mean something. Calling a symptom "worsening" off two or three entries
        # is the kind of false alarm that worries people about their health;
        # below the minimum we don't classify it.
        if len(severities) >= 5:
            mid = len(severities) // 2
            first_avg = sum(severities[:mid]) / mid
            last_avg  = sum(severities[mid:]) / (len(severities) - mid)
            if last_avg - first_avg > 0.5:
                trend = 'worsening'
            elif first_avg - last_avg > 0.5:
                trend = 'improving'
            else:
                trend = 'stable'
        else:
            trend = 'insufficient'

        # Unique days this appeared
        days_list = sorted(set(e['date_key'] for e in entries))

        symptoms.append({
            'name':          name,
            'count':         len(entries),
            'days_affected': len(days_list),
            'recent_count':  len(recent),
            'avg_severity':  round(sum(severities) / len(severities), 1),
            'max_severity':  max(severities),
            'peak_time':     peak_time,
            'trend':         trend,
            'last_seen':     sorted_entries[-1]['date_key'],
            'first_seen':    sorted_entries[0]['date_key'],
            'severity_history': [
                {'date': e['date_key'], 'severity': e['severity']}
                for e in sorted_entries
            ],
        })

    # Sort by recent activity first, then total count
    symptoms.sort(key=lambda x: (x['recent_count'], x['count']), reverse=True)

    # ── alerts (3+ occurrences in last 7 days) ───────────────────
    alerts = [
        {
            'name':         s['name'],
            'count':        s['recent_count'],
            'avg_severity': s['avg_severity'],
            'peak_time':    s['peak_time'],
        }
        for s in symptoms if s['recent_count'] >= 3
    ]

    # ── co-occurrence ────────────────────────────────────────────
    by_date = defaultdict(set)
    for r in rows:
        by_date[r['date_key']].add(r['name'])

    pair_counts = Counter()
    for day_syms in by_date.values():
        day_list = sorted(day_syms)
        for i in range(len(day_list)):
            for j in range(i+1, len(day_list)):
                pair_counts[(day_list[i], day_list[j])] += 1

    co_occur = [
        {'a': a, 'b': b, 'count': c}
        for (a, b), c in pair_counts.most_common(5)
        if c >= 2
    ]

    # ── heatmap: last 30 days × symptom names ────────────────────
    top_names = [s['name'] for s in symptoms[:6]]
    date_range = [(today - dt.timedelta(days=i)).isoformat() for i in range(days-1, -1, -1)]
    heatmap = {name: {d: 0 for d in date_range} for name in top_names}
    for r in rows:
        if r['name'] in heatmap and r['date_key'] in heatmap[r['name']]:
            heatmap[r['name']][r['date_key']] = r['severity']

    return jsonify({
        'days':        days,
        'total_logs':  len(rows),
        'symptoms':    symptoms,
        'alerts':      alerts,
        'co_occur':    co_occur,
        'heatmap': {
            'names': top_names,
            'dates': date_range[-14:],   # last 14 days for display
            'data':  {n: [heatmap[n][d] for d in date_range[-14:]] for n in top_names},
        },
    })


@bp.route('/api/symptoms/correlations')
@require_auth
def api_symptom_correlations():
    """Cross-factor patterns: does a symptom line up with short sleep, the start
    of a medicine, or the menstrual cycle? Patterns only — never a diagnosis."""
    from db.symptom_insights import get_symptom_correlations
    days = request.args.get('days', 60)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 60
    return jsonify(get_symptom_correlations(days))

@bp.route('/api/metrics/options')
@require_auth
def api_metric_options():
    from db.metric_insights import get_correlatable_metrics
    return jsonify(get_correlatable_metrics())

@bp.route('/api/metrics/correlation')
@require_auth
def api_metric_correlation():
    from db.metric_insights import get_metric_correlation
    a = request.args.get('a', ''); b = request.args.get('b', '')
    days = int(request.args.get('days', 90)) if str(request.args.get('days', 90)).isdigit() else 90
    return jsonify(get_metric_correlation(a, b, days))

@bp.route('/api/symptoms/med-effect')
@require_auth
def api_symptom_med_effect():
    """Before-vs-after a medicine change, for each symptom — an observation from
    the user's own logs, never a proven cause."""
    from db.symptom_insights import get_symptom_med_effectiveness
    return jsonify(get_symptom_med_effectiveness())



# ── Vitals ────────────────────────────────────────────────────────────────────
@bp.route('/api/vitals')
@require_auth
def api_vitals():
    return jsonify(get_vitals())

@bp.route('/api/peak-flow')
@require_auth
def api_peak_flow():
    """Peak-flow readings zoned green/yellow/red against the user's personal best."""
    from db.peak_flow import get_peak_flow_state
    days = to_int(request.args.get('days', 180), 180, lo=1, hi=3650)
    return jsonify(get_peak_flow_state(days))

@bp.route('/api/vitals/baselines')
@require_auth
def api_vital_baselines():
    """Personal baseline bands (your own mean ± 1 SD) for core vitals (J7)."""
    from db.baselines import get_personal_baselines
    days = to_int(request.args.get('days', 180), 180, lo=7, hi=3650)
    return jsonify(get_personal_baselines(days))

@bp.route('/api/vitals/estimated-a1c')
@require_auth
def api_estimated_a1c():
    """Estimated HbA1c from logged glucose (ADAG formula) — an estimate (K2)."""
    from db.glucose_a1c import estimate_a1c
    days = to_int(request.args.get('days', 90), 90, lo=14, hi=365)
    return jsonify(estimate_a1c(days))

@bp.route('/api/vitals/bp-home-clinic')
@require_auth
def api_bp_home_clinic():
    """Home vs clinic BP (white-coat effect, K4)."""
    from db.bp_patterns import get_bp_home_vs_clinic
    days = to_int(request.args.get('days', 180), 180, lo=7, hi=3650)
    return jsonify(get_bp_home_vs_clinic(days))

@bp.route('/api/vitals/bp-time-pattern')
@require_auth
def api_bp_time_pattern():
    """Morning vs evening BP (K5)."""
    from db.bp_patterns import get_bp_time_pattern
    days = to_int(request.args.get('days', 180), 180, lo=7, hi=3650)
    return jsonify(get_bp_time_pattern(days))


# ── Emergency action plans (J3) ─────────────────────────────────────────────
@bp.route('/api/action-plans', methods=['GET'])
@require_auth
def api_action_plans():
    from db.action_plans import list_action_plans, PLAN_SUGGESTIONS
    return jsonify({'plans': list_action_plans(), 'suggestions': list(PLAN_SUGGESTIONS)})

@bp.route('/api/action-plans', methods=['POST'])
@require_auth
def api_create_action_plan():
    from db.action_plans import create_action_plan
    try:
        p = create_action_plan(request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'plan': p})

@bp.route('/api/action-plans/<pid>', methods=['PUT'])
@require_auth
def api_update_action_plan(pid):
    from db.action_plans import update_action_plan
    try:
        p = update_action_plan(pid, request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    return jsonify({'success': True, 'plan': p})

@bp.route('/api/action-plans/<pid>', methods=['DELETE'])
@require_auth
def api_delete_action_plan(pid):
    from db.action_plans import delete_action_plan
    delete_action_plan(pid)
    return jsonify({'success': True})

@bp.route('/api/vitals', methods=['POST'])
@require_auth
def api_log_vital():
    try:
        v = log_vital(request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'vital': v})

@bp.route('/api/vitals/<vid>', methods=['DELETE'])
@require_auth
def api_del_vital(vid):
    delete_vital(vid)
    return jsonify({'success': True})
@bp.route('/api/vitals/trend')
@require_auth
def api_vitals_trend():
    """Return 30-day vitals grouped by type, shaped for charting."""
    import datetime as dt
    days  = int(request.args.get('days', 30))
    vtype = request.args.get('type')          # optional filter
    rows  = get_vitals(vtype=vtype, days=days)

    # Group by type, sorted oldest-first for chart rendering
    from collections import defaultdict
    groups = defaultdict(list)
    for r in reversed(rows):                  # reversed = oldest first
        groups[r['type']].append({
            'date':   r['date_key'],
            'value1': r['value1'],
            'value2': r['value2'],
            'unit':   r['unit'],
            'id':     r['id'],
        })

    # Reference ranges for context lines
    RANGES = {
        'blood_pressure': {'sys_min':90,'sys_max':120,'dia_min':60,'dia_max':80,
                           'sys_high':140,'dia_high':90},
        'heart_rate':     {'min':60,'max':100},
        'blood_sugar':    {'min':70,'max':99,'pre':125},
        'spo2':           {'min':95},
        'temperature':    {'min':36.1,'max':37.2},
    }

    # Human-readable band label, shown so "in range" is never a black box.
    BANDS = {
        'blood_pressure': '90–120 / 60–80 mmHg',
        'heart_rate':     '60–100 bpm',
        'blood_sugar':    '70–99 mg/dL',
        'spo2':           '≥ 95%',
        'temperature':    '36.1–37.2 °C',
    }

    def _classify(vtype, v1, v2):
        """'in' / 'low' / 'high' against the reference band, or None if unknown."""
        R = RANGES.get(vtype)
        if R is None or v1 is None:
            return None
        if vtype == 'blood_pressure':
            if v2 is None:
                return None
            if v1 > R['sys_max'] or v2 > R['dia_max']:
                return 'high'
            if v1 < R['sys_min'] or v2 < R['dia_min']:
                return 'low'
            return 'in'
        if 'min' in R and 'max' in R:
            return 'high' if v1 > R['max'] else 'low' if v1 < R['min'] else 'in'
        if 'min' in R:                       # spo2: only a floor
            return 'low' if v1 < R['min'] else 'in'
        return None

    # Time-in-range: what share of readings sat inside the reference band.
    # Factual only — it reports counts against a stated band, never a verdict.
    tir = {}
    for vtype, entries in groups.items():
        counts = {'in': 0, 'low': 0, 'high': 0}
        for e in entries:
            c = _classify(vtype, e.get('value1'), e.get('value2'))
            if c:
                counts[c] += 1
        total = sum(counts.values())
        if total >= 3:                       # too few readings to bother
            tir[vtype] = {**counts, 'total': total,
                          'pct': round(counts['in'] / total * 100),
                          'band': BANDS.get(vtype, '')}

    return jsonify({
        'days':   days,
        'groups': dict(groups),
        'ranges': RANGES,
        'tir':    tir,
        'total':  len(rows),
    })



# ── Emergency info ────────────────────────────────────────────────────────────
@bp.route('/api/emergency')
@require_auth
def api_emergency():
    return jsonify(get_emergency_info())

@bp.route('/api/emergency', methods=['POST'])
@require_auth
def api_save_emergency():
    save_emergency_info(request.json or {})
    return jsonify({'success': True})

# ── Wellness strip (dashboard) ────────────────────────────────────────────────
@bp.route('/api/wellness/today')
@require_auth
def api_wellness_today():
    today = today_iso(get_user_timezone())
    hyd   = get_hydration_day(today)
    sl    = get_sleep_logs(1)
    hab   = get_habit_stats(1)
    sym   = get_symptoms(1)
    return jsonify({
        'hydration': hyd,
        'sleep':     sl[0] if sl else None,
        'habits': {
            'done':  sum(1 for h in hab['habits'] if h.get('done_today')),
            'total': len(hab['habits'])
        },
        'symptoms': len([s for s in sym if s['date_key'] == today])
    })


# ── Reminder settings ─────────────────────────────────────────────────────────

@bp.route('/api/reminders/settings')
@require_auth
def api_get_reminder_settings():
    from db.core import execute, new_id, now_iso, current_user_id
    uid = current_user_id()
    row = execute("SELECT * FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if not row:
        # Create defaults
        rid = new_id()
        execute("""INSERT INTO reminder_settings
            (id,water_enabled,water_interval_h,water_start,water_end,water_goal_ml,
             habit_reminder_enabled,habit_reminder_time,
             sleep_reminder_enabled,sleep_reminder_time,
             mood_reminder_enabled,mood_reminder_time,updated_at,user_id)
            VALUES (?,1,2.0,'08:00','21:00',2450,1,'20:00',1,'22:00',1,'18:00',?,?)""",
            (rid, now_iso(), uid), commit=True)
        row = execute("SELECT * FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    return jsonify(dict(row))

@bp.route('/api/reminders/settings', methods=['POST'])
@require_auth
def api_save_reminder_settings():
    import re as _re
    from db.core import execute, new_id, now_iso, current_user_id
    uid = current_user_id()
    d = request.json or {}

    _time_re = _re.compile(r'^([01]?\d|2[0-3]):[0-5]\d$')
    def _time(key, default):
        v = str(d.get(key, default)).strip()
        return v if _time_re.match(v) else default
    def _bool(key, default=1):
        return 1 if to_int(d.get(key, default), default, lo=0, hi=1) else 0

    # Coerce/validate everything once so a bad payload can't brick the day view
    water_enabled   = _bool('water_enabled')
    water_interval  = to_num(d.get('water_interval_h', 2.0), 2.0, lo=0.25, hi=24)
    water_start     = _time('water_start', '08:00')
    water_end       = _time('water_end', '21:00')
    water_goal_ml   = to_int(d.get('water_goal_ml', 2450), 2450, lo=0, hi=20000)
    habit_enabled   = _bool('habit_reminder_enabled')
    habit_time      = _time('habit_reminder_time', '20:00')
    sleep_enabled   = _bool('sleep_reminder_enabled')
    sleep_time      = _time('sleep_reminder_time', '22:00')
    mood_enabled    = _bool('mood_reminder_enabled')
    mood_time       = _time('mood_reminder_time', '18:00')
    quiet_enabled   = _bool('quiet_enabled', 0)
    quiet_start     = _time('quiet_start', '22:00')
    quiet_end       = _time('quiet_end', '07:00')
    low_key         = _bool('low_key', 0)
    snooze_default  = to_int(d.get('default_snooze_min', 10), 10, lo=1, hi=180)

    row = execute("SELECT id FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if row:
        # digest flags: preserve the stored value when the client doesn't send
        # it (the unsubscribe links must survive settings saves)
        current = execute("""SELECT weekly_digest_enabled, caregiver_digest_enabled
                             FROM reminder_settings WHERE id=?""",
                          (row['id'],), fetchone=True) or {}
        digest_flag = _bool('weekly_digest_enabled',
                            current.get('weekly_digest_enabled', 1) or 0)
        cg_digest_flag = _bool('caregiver_digest_enabled',
                               current.get('caregiver_digest_enabled', 1) or 0)
        execute("""UPDATE reminder_settings SET
            water_enabled=?, water_interval_h=?, water_start=?, water_end=?,
            water_goal_ml=?, habit_reminder_enabled=?, habit_reminder_time=?,
            sleep_reminder_enabled=?, sleep_reminder_time=?,
            mood_reminder_enabled=?, mood_reminder_time=?,
            quiet_enabled=?, quiet_start=?, quiet_end=?, low_key=?,
            default_snooze_min=?,
            weekly_digest_enabled=?, caregiver_digest_enabled=?, updated_at=?
            WHERE id=?""",
            (water_enabled, water_interval, water_start, water_end,
             water_goal_ml, habit_enabled, habit_time,
             sleep_enabled, sleep_time,
             mood_enabled, mood_time,
             quiet_enabled, quiet_start, quiet_end, low_key,
             snooze_default,
             digest_flag, cg_digest_flag,
             now_iso(), row['id']), commit=True)
    else:
        rid = new_id()
        execute("""INSERT INTO reminder_settings
            (id,water_enabled,water_interval_h,water_start,water_end,water_goal_ml,
             habit_reminder_enabled,habit_reminder_time,
             sleep_reminder_enabled,sleep_reminder_time,
             mood_reminder_enabled,mood_reminder_time,
             quiet_enabled,quiet_start,quiet_end,low_key,default_snooze_min,updated_at,user_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, water_enabled, water_interval,
             water_start, water_end, water_goal_ml,
             habit_enabled, habit_time,
             sleep_enabled, sleep_time,
             mood_enabled, mood_time,
             quiet_enabled, quiet_start, quiet_end, low_key, snooze_default,
             now_iso(), uid), commit=True)
    updated = execute("SELECT * FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    return jsonify({'success': True, 'settings': dict(updated)})

@bp.route('/api/digest/unsubscribe/<token>')
def api_digest_unsubscribe(token):
    """One-click unsubscribe from weekly digest emails (link in the email —
    no login required, the signed token identifies the user)."""
    from auth import read_digest_unsub_token
    from db.core import execute, new_id, now_iso
    uid = read_digest_unsub_token(token)
    if not uid:
        return '<h3>This unsubscribe link is invalid or has expired.</h3>', 400
    row = execute("SELECT id FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if row:
        execute("UPDATE reminder_settings SET weekly_digest_enabled=0, updated_at=? WHERE id=?",
                (now_iso(), row['id']), commit=True)
    else:
        execute("""INSERT INTO reminder_settings (id, weekly_digest_enabled, updated_at, user_id)
                   VALUES (?, 0, ?, ?)""", (new_id(), now_iso(), uid), commit=True)
    return ('<div style="font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center">'
            '<h2>You\'re unsubscribed 👋</h2>'
            '<p>You won\'t receive the weekly digest email anymore. '
            'You can turn it back on any time in Notifications → Settings.</p>'
            '<p><a href="/">Back to Arogo</a></p></div>')


@bp.route('/api/caregiver-digest/unsubscribe/<token>')
def api_caregiver_digest_unsubscribe(token):
    """One-click unsubscribe from the caregiver weekly digest (signed token)."""
    from auth import read_caregiver_digest_unsub_token
    from db.core import execute, new_id, now_iso
    uid = read_caregiver_digest_unsub_token(token)
    if not uid:
        return '<h3>This unsubscribe link is invalid or has expired.</h3>', 400
    row = execute("SELECT id FROM reminder_settings WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if row:
        execute("UPDATE reminder_settings SET caregiver_digest_enabled=0, updated_at=? WHERE id=?",
                (now_iso(), row['id']), commit=True)
    else:
        execute("""INSERT INTO reminder_settings (id, caregiver_digest_enabled, updated_at, user_id)
                   VALUES (?, 0, ?, ?)""", (new_id(), now_iso(), uid), commit=True)
    return ('<div style="font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center">'
            '<h2>You\'re unsubscribed 👋</h2>'
            '<p>You won\'t receive the weekly caregiver digest anymore. '
            'You can turn it back on any time in Notifications → Settings.</p>'
            '<p><a href="/">Back to Arogo</a></p></div>')


@bp.route('/api/reminders/water-status')
@require_auth
def api_water_status():
    """Return today's hydration status for smart reminder logic."""
    from db.core import today_iso
    hyd = get_hydration_day(today_iso(get_user_timezone()))
    return jsonify({
        'total_ml':  hyd.get('total_ml', 0),
        'goal_ml':   hyd.get('goal_ml', 2450),
        'pct':       hyd.get('pct', 0),
        'last_log':  hyd['logs'][-1]['logged_at'] if hyd.get('logs') else None,
        'on_track':  hyd.get('pct', 0) >= 50,
    })

# ── Notifications ─────────────────────────────────────────────────────────────
@bp.route('/api/notifications')
@require_auth
def api_get_notifications():
    limit = int(request.args.get('limit', 50))
    unread_only = request.args.get('unread') == '1'
    notes = get_notifications(limit, unread_only)
    return jsonify({'notifications': notes, 'unread': unread_notification_count()})

@bp.route('/api/notifications', methods=['POST'])
@require_auth
def api_add_notification_route():
    d = request.json or {}
    n = add_notification(d.get('type','system'), d.get('title',''),
                         d.get('body',''), d.get('source_id'))
    return jsonify({'success': True, 'notification': n})

@bp.route('/api/notifications/<nid>/read', methods=['POST'])
@require_auth
def api_mark_read(nid):
    mark_notification_read(nid)
    return jsonify({'success': True, 'unread': unread_notification_count()})

@bp.route('/api/notifications/read-all', methods=['POST'])
@require_auth
def api_mark_all_read():
    mark_all_notifications_read()
    return jsonify({'success': True})