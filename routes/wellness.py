"""routes/wellness.py — Hydration, sleep, body metrics, thoughts, todos,
   habits, symptoms, vitals, emergency, medicine stock, notifications."""
from flask import Blueprint, request, jsonify
from db import *

bp = Blueprint("wellness", __name__)

# ── Medicine stock ────────────────────────────────────────────────────────────
@bp.route('/api/medicines/<mid>/stock', methods=['POST'])
def api_update_stock(mid):
    d = request.json or {}
    m = update_medicine_stock(mid, int(d.get('pill_count',0)),
                              int(d.get('pills_per_dose',1)),
                              int(d.get('refill_threshold',7)))
    return jsonify({'success': True, 'medicine': m})

@bp.route('/api/medicines/low-stock')
def api_low_stock():
    return jsonify(get_low_stock_medicines())

@bp.route('/api/medicines/adherence')
def api_med_adherence():
    return jsonify({'medicines': list_medicines()})
@bp.route('/api/medicines/streaks')
def api_medicine_streaks():
    """
    Per-medicine streak + adherence data for the last 30 days.
    Returns streak, best streak, 30-day dot grid, overall adherence %.
    """
    import datetime as dt
    from db.medicines import list_medicines
    from db.core import execute

    days     = int(request.args.get('days', 30))
    today    = dt.date.today()
    meds     = [m for m in list_medicines() if m['active']]

    # Date range: oldest first
    date_range = [(today - dt.timedelta(days=i)).isoformat()
                  for i in range(days - 1, -1, -1)]

    overall_total = 0
    overall_taken = 0
    results = []

    for m in meds:
        times    = m.get('times', []) or ['08:00']
        mid      = m['id']
        expected = len(times)   # doses expected per day

        # Fetch all dose_logs for this medicine in range
        logs = execute(
            """SELECT date_key, time_key, taken FROM dose_logs
               WHERE medicine_id=? AND date_key >= ? ORDER BY date_key""",
            (mid, date_range[0]), fetchall=True)
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

        # Streak = consecutive fully-taken days counting BACK from today
        streak = 0
        for d in reversed(day_data):
            if d['full']:
                streak += 1
            else:
                break

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
def api_hydration_day(date_key):
    return jsonify(get_hydration_day(date_key))

@bp.route('/api/hydration/week')
def api_hydration_week():
    return jsonify(get_hydration_week())

@bp.route('/api/hydration', methods=['POST'])
def api_log_hydration():
    d = request.json or {}
    log_hydration(d.get('amount_ml', 250), d.get('drink_type','water'),
                  d.get('date_key', today_iso()))
    return jsonify({'success': True})

@bp.route('/api/hydration/<lid>', methods=['DELETE'])
def api_del_hydration(lid):
    delete_hydration_log(lid)
    return jsonify({'success': True})

# ── Sleep ─────────────────────────────────────────────────────────────────────
@bp.route('/api/sleep')
def api_sleep():
    days = int(request.args.get('days', 14))
    return jsonify(get_sleep_logs(days))

@bp.route('/api/sleep', methods=['POST'])
def api_log_sleep():
    s = log_sleep(request.json or {})
    return jsonify({'success': True, 'log': s})

@bp.route('/api/sleep/<lid>', methods=['DELETE'])
def api_del_sleep(lid):
    delete_sleep_log(lid)
    return jsonify({'success': True})
@bp.route('/api/sleep/trend')
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

    # Trend: compare first half vs second half duration
    mid        = len(durations) // 2 or 1
    first_avg  = sum(durations[:mid]) / mid
    second_avg = sum(durations[mid:]) / max(len(durations[mid:]), 1)
    if second_avg - first_avg > 0.2:
        dur_trend = 'improving'
    elif first_avg - second_avg > 0.2:
        dur_trend = 'worsening'
    else:
        dur_trend = 'stable'

    # Days with 7h+ (recommended)
    good_nights = sum(1 for d in durations if d >= 7)

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
        },
        'weekly': weekly,
    })



# ── Body metrics ──────────────────────────────────────────────────────────────
@bp.route('/api/body-metrics')
def api_body_metrics():
    return jsonify(get_body_metrics())

@bp.route('/api/body-metrics', methods=['POST'])
def api_log_body():
    m = log_body_metric(request.json or {})
    return jsonify({'success': True, 'metric': m})
@bp.route('/api/body-metrics/trend')
def api_body_metrics_trend():
    """All-time weight data + goal projection line."""
    import datetime as dt
    from db.core import execute
    from db.food import get_profile, calc_tdee

    days   = int(request.args.get('days', 365))
    start  = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows   = execute(
        "SELECT date_key, weight_kg, body_fat_pct, bmi FROM body_metrics "
        "WHERE weight_kg IS NOT NULL AND date_key >= ? ORDER BY date_key",
        (start,), fetchall=True)
    logs   = [dict(r) for r in rows]

    profile = get_profile()
    targets = calc_tdee(profile)

    start_weight  = logs[0]['weight_kg']  if logs else None
    latest_weight = logs[-1]['weight_kg'] if logs else None
    target_weight = profile.get('target_weight_kg')
    goal          = profile.get('goal', 'maintain')
    current_weight = float(profile.get('weight_kg', 70))

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

    # Estimated arrival date
    eta_date = None
    if projection:
        last_proj = projection[-1]
        if abs(last_proj['weight'] - target_weight) < 0.1:
            eta_date = last_proj['date']

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
            'logged_entries': len(logs),
        },
    })



# ── Thoughts / Journal ────────────────────────────────────────────────────────
@bp.route('/api/thoughts/<date_key>')
def api_get_thoughts(date_key):
    return jsonify(get_thoughts(date_key))

@bp.route('/api/thoughts', methods=['POST'])
def api_save_thought():
    d = request.json or {}
    t = save_thought(d.get('content',''), d.get('mood','neutral'), d.get('date_key', today_iso()))
    return jsonify({'success': True, 'thought': t})

@bp.route('/api/thoughts/<tid>', methods=['PUT'])
def api_update_thought(tid):
    d = request.json or {}
    t = update_thought(tid, d.get('content',''), d.get('mood','neutral'))
    return jsonify({'success': True, 'thought': t})

@bp.route('/api/thoughts/<tid>', methods=['DELETE'])
def api_del_thought(tid):
    delete_thought(tid)
    return jsonify({'success': True})

@bp.route('/api/thoughts')
def api_thoughts_list():
    return jsonify(get_thoughts_range(30))

# ── Todos ─────────────────────────────────────────────────────────────────────
@bp.route('/api/todos')
def api_todos():
    return jsonify({'todos': list_todos()})

@bp.route('/api/todos', methods=['POST'])
def api_create_todo():
    t = create_todo(request.json or {})
    return jsonify({'success': True, 'todo': t})

@bp.route('/api/todos/<tid>', methods=['PUT'])
def api_update_todo(tid):
    t = update_todo(tid, request.json or {})
    return jsonify({'success': True, 'todo': t})

@bp.route('/api/todos/<tid>', methods=['DELETE'])
def api_del_todo(tid):
    delete_todo(tid)
    return jsonify({'success': True})

@bp.route('/api/todos/<tid>/toggle', methods=['POST'])
def api_toggle_todo(tid):
    toggle_todo(tid)
    return jsonify({'success': True})

@bp.route('/api/todos/reminders/due')
def api_due_reminders():
    return jsonify(get_due_reminders())

# ── Habits ────────────────────────────────────────────────────────────────────
@bp.route('/api/habits')
def api_habits():
    return jsonify(get_habit_stats())

@bp.route('/api/habits', methods=['POST'])
def api_create_habit():
    h = create_habit(request.json or {})
    return jsonify({'success': True, 'habit': h})

@bp.route('/api/habits/<hid>', methods=['DELETE'])
def api_del_habit(hid):
    delete_habit(hid)
    return jsonify({'success': True})

@bp.route('/api/habits/<hid>/toggle', methods=['POST'])
def api_toggle_habit(hid):
    d = request.json or {}
    toggle_habit_log(hid, d.get('date_key', today_iso()))
    return jsonify({'success': True, 'done': True})

# ── Symptoms ──────────────────────────────────────────────────────────────────
@bp.route('/api/symptoms')
def api_symptoms():
    days = int(request.args.get('days', 14))
    return jsonify(get_symptoms(days))

@bp.route('/api/symptoms', methods=['POST'])
def api_log_symptom():
    s = log_symptom(request.json or {})
    return jsonify({'success': True, 'symptom': s})

@bp.route('/api/symptoms/<sid>', methods=['DELETE'])
def api_del_symptom(sid):
    delete_symptom(sid)
    return jsonify({'success': True})
@bp.route('/api/symptoms/patterns')
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

        # Severity trend — compare first half vs second half
        mid = len(severities) // 2 or 1
        first_avg = sum(severities[:mid]) / mid
        last_avg  = sum(severities[mid:]) / max(len(severities[mid:]), 1)
        if last_avg - first_avg > 0.5:
            trend = 'worsening'
        elif first_avg - last_avg > 0.5:
            trend = 'improving'
        else:
            trend = 'stable'

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



# ── Vitals ────────────────────────────────────────────────────────────────────
@bp.route('/api/vitals')
def api_vitals():
    return jsonify(get_vitals())

@bp.route('/api/vitals', methods=['POST'])
def api_log_vital():
    v = log_vital(request.json or {})
    return jsonify({'success': True, 'vital': v})

@bp.route('/api/vitals/<vid>', methods=['DELETE'])
def api_del_vital(vid):
    delete_vital(vid)
    return jsonify({'success': True})
@bp.route('/api/vitals/trend')
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

    return jsonify({
        'days':   days,
        'groups': dict(groups),
        'ranges': RANGES,
        'total':  len(rows),
    })



# ── Emergency info ────────────────────────────────────────────────────────────
@bp.route('/api/emergency')
def api_emergency():
    return jsonify(get_emergency_info())

@bp.route('/api/emergency', methods=['POST'])
def api_save_emergency():
    save_emergency_info(request.json or {})
    return jsonify({'success': True})

# ── Wellness strip (dashboard) ────────────────────────────────────────────────
@bp.route('/api/wellness/today')
def api_wellness_today():
    today = today_iso()
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
def api_get_reminder_settings():
    from db.core import execute, new_id, now_iso
    row = execute("SELECT * FROM reminder_settings LIMIT 1", fetchone=True)
    if not row:
        # Create defaults
        rid = new_id()
        execute("""INSERT INTO reminder_settings
            (id,water_enabled,water_interval_h,water_start,water_end,water_goal_ml,
             habit_reminder_enabled,habit_reminder_time,
             sleep_reminder_enabled,sleep_reminder_time,
             mood_reminder_enabled,mood_reminder_time,updated_at)
            VALUES (?,1,2.0,'08:00','21:00',2450,1,'20:00',1,'22:00',1,'18:00',?)""",
            (rid, now_iso()), commit=True)
        row = execute("SELECT * FROM reminder_settings LIMIT 1", fetchone=True)
    return jsonify(dict(row))

@bp.route('/api/reminders/settings', methods=['POST'])
def api_save_reminder_settings():
    from db.core import execute, new_id, now_iso
    d = request.json or {}
    row = execute("SELECT id FROM reminder_settings LIMIT 1", fetchone=True)
    if row:
        execute("""UPDATE reminder_settings SET
            water_enabled=?, water_interval_h=?, water_start=?, water_end=?,
            water_goal_ml=?, habit_reminder_enabled=?, habit_reminder_time=?,
            sleep_reminder_enabled=?, sleep_reminder_time=?,
            mood_reminder_enabled=?, mood_reminder_time=?, updated_at=?
            WHERE id=?""",
            (int(d.get('water_enabled', 1)),
             float(d.get('water_interval_h', 2.0)),
             d.get('water_start', '08:00'),
             d.get('water_end', '21:00'),
             int(d.get('water_goal_ml', 2450)),
             int(d.get('habit_reminder_enabled', 1)),
             d.get('habit_reminder_time', '20:00'),
             int(d.get('sleep_reminder_enabled', 1)),
             d.get('sleep_reminder_time', '22:00'),
             int(d.get('mood_reminder_enabled', 1)),
             d.get('mood_reminder_time', '18:00'),
             now_iso(), row['id']), commit=True)
    else:
        rid = new_id()
        execute("""INSERT INTO reminder_settings
            (id,water_enabled,water_interval_h,water_start,water_end,water_goal_ml,
             habit_reminder_enabled,habit_reminder_time,
             sleep_reminder_enabled,sleep_reminder_time,
             mood_reminder_enabled,mood_reminder_time,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, int(d.get('water_enabled',1)),
             float(d.get('water_interval_h',2.0)),
             d.get('water_start','08:00'), d.get('water_end','21:00'),
             int(d.get('water_goal_ml',2450)),
             int(d.get('habit_reminder_enabled',1)), d.get('habit_reminder_time','20:00'),
             int(d.get('sleep_reminder_enabled',1)), d.get('sleep_reminder_time','22:00'),
             int(d.get('mood_reminder_enabled',1)), d.get('mood_reminder_time','18:00'),
             now_iso()), commit=True)
    updated = execute("SELECT * FROM reminder_settings LIMIT 1", fetchone=True)
    return jsonify({'success': True, 'settings': dict(updated)})

@bp.route('/api/reminders/water-status')
def api_water_status():
    """Return today's hydration status for smart reminder logic."""
    from db.core import today_iso
    hyd = get_hydration_day(today_iso())
    return jsonify({
        'total_ml':  hyd.get('total_ml', 0),
        'goal_ml':   hyd.get('goal_ml', 2450),
        'pct':       hyd.get('pct', 0),
        'last_log':  hyd['logs'][-1]['logged_at'] if hyd.get('logs') else None,
        'on_track':  hyd.get('pct', 0) >= 50,
    })

# ── Notifications ─────────────────────────────────────────────────────────────
@bp.route('/api/notifications')
def api_get_notifications():
    limit = int(request.args.get('limit', 50))
    unread_only = request.args.get('unread') == '1'
    notes = get_notifications(limit, unread_only)
    return jsonify({'notifications': notes, 'unread': unread_notification_count()})

@bp.route('/api/notifications', methods=['POST'])
def api_add_notification_route():
    d = request.json or {}
    n = add_notification(d.get('type','system'), d.get('title',''),
                         d.get('body',''), d.get('source_id'))
    return jsonify({'success': True, 'notification': n})

@bp.route('/api/notifications/<nid>/read', methods=['POST'])
def api_mark_read(nid):
    mark_notification_read(nid)
    return jsonify({'success': True, 'unread': unread_notification_count()})

@bp.route('/api/notifications/read-all', methods=['POST'])
def api_mark_all_read():
    mark_all_notifications_read()
    return jsonify({'success': True})