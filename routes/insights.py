"""routes/insights.py — Health report, goal progress, global search, data export, notifications."""
from flask import Blueprint, request, jsonify, send_from_directory, current_app
import os, json as json_mod
from db import *
from config import Config

import csv, io, datetime as dt_mod
bp = Blueprint("insights", __name__)

@bp.route('/api/report/weekly')
def api_weekly_report():
    return jsonify(generate_weekly_report())

# ══════════════════════════════════════════════════════════════════════════════
# Goal Progress
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/progress')
def api_goal_progress():
    return jsonify(get_goal_progress())

# ══════════════════════════════════════════════════════════════════════════════
# Global Search
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/search')
def api_global_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'query': q, 'total': 0, 'sections': []})
    return jsonify(global_search(q))

# ══════════════════════════════════════════════════════════════════════════════
# Data Export
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/export/counts')
def api_export_counts():
    """Return row counts per section for the export preview."""
    from database import execute
    from_date = request.args.get('from', '2000-01-01')
    to_date   = request.args.get('to',   today_iso())
    counts = {
        'food_logs':          execute("SELECT COUNT(*) as n FROM food_logs WHERE date_key BETWEEN ? AND ?",       (from_date, to_date), fetchone=True)['n'],
        'fitness_activities': execute("SELECT COUNT(*) as n FROM fitness_activities WHERE date BETWEEN ? AND ?",  (from_date, to_date), fetchone=True)['n'],
        'sleep_logs':         execute("SELECT COUNT(*) as n FROM sleep_logs WHERE date_key BETWEEN ? AND ?",      (from_date, to_date), fetchone=True)['n'],
        'symptoms':           execute("SELECT COUNT(*) as n FROM symptoms WHERE date_key BETWEEN ? AND ?",        (from_date, to_date), fetchone=True)['n'],
        'vitals':             execute("SELECT COUNT(*) as n FROM vitals WHERE date_key BETWEEN ? AND ?",          (from_date, to_date), fetchone=True)['n'],
        'thoughts':           execute("SELECT COUNT(*) as n FROM thoughts WHERE date_key BETWEEN ? AND ?",        (from_date, to_date), fetchone=True)['n'],
        'todos':              execute("SELECT COUNT(*) as n FROM todos WHERE created_at BETWEEN ? AND ?",         (from_date, to_date+'T23:59:59'), fetchone=True)['n'],
        'body_metrics':       execute("SELECT COUNT(*) as n FROM body_metrics WHERE date_key BETWEEN ? AND ?",    (from_date, to_date), fetchone=True)['n'],
        'hydration_logs':     execute("SELECT COUNT(*) as n FROM hydration_logs WHERE date_key BETWEEN ? AND ?",  (from_date, to_date), fetchone=True)['n'],
        'habits':             execute("SELECT COUNT(*) as n FROM habits WHERE active=1",                          fetchone=True)['n'],
        'medicines':          execute("SELECT COUNT(*) as n FROM medicines WHERE active=1",                       fetchone=True)['n'],
    }
    return jsonify(counts)

@bp.route('/api/export')
def api_export():
    import csv, io, datetime as dt_mod
    fmt       = request.args.get('format', 'json')
    sections  = request.args.get('sections', 'all')  # comma-separated or 'all'
    from_date = request.args.get('from', '2000-01-01')
    to_date   = request.args.get('to', today_iso())

    wanted = sections.split(',') if sections != 'all' else None
    def want(k): return wanted is None or k in wanted

    from database import execute
    data = {}

    if want('food_logs'):
        rows = execute("SELECT * FROM food_logs WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['food_logs'] = [dict(r) for r in rows]
    if want('fitness_activities'):
        rows = execute("SELECT * FROM fitness_activities WHERE date BETWEEN ? AND ? ORDER BY date DESC", (from_date, to_date), fetchall=True)
        data['fitness_activities'] = [dict(r) for r in rows]
    if want('sleep_logs'):
        rows = execute("SELECT * FROM sleep_logs WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['sleep_logs'] = [dict(r) for r in rows]
    if want('symptoms'):
        rows = execute("SELECT * FROM symptoms WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['symptoms'] = [dict(r) for r in rows]
    if want('vitals'):
        rows = execute("SELECT * FROM vitals WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['vitals'] = [dict(r) for r in rows]
    if want('thoughts'):
        rows = execute("SELECT * FROM thoughts WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['thoughts'] = [dict(r) for r in rows]
    if want('todos'):
        rows = execute("SELECT * FROM todos WHERE created_at BETWEEN ? AND ? ORDER BY created_at DESC", (from_date, to_date+'T23:59:59'), fetchall=True)
        data['todos'] = [dict(r) for r in rows]
    if want('body_metrics'):
        rows = execute("SELECT * FROM body_metrics WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['body_metrics'] = [dict(r) for r in rows]
    if want('hydration_logs'):
        rows = execute("SELECT * FROM hydration_logs WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['hydration_logs'] = [dict(r) for r in rows]
    if want('habits'):
        rows = execute("SELECT * FROM habits WHERE active=1 ORDER BY created_at", fetchall=True)
        data['habits'] = [dict(r) for r in rows]
        log_rows = execute("SELECT * FROM habit_logs WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC", (from_date, to_date), fetchall=True)
        data['habit_logs'] = [dict(r) for r in log_rows]
    if want('medicines'):
        rows = execute("SELECT * FROM medicines WHERE active=1 ORDER BY name", fetchall=True)
        data['medicines'] = [dict(r) for r in rows]

    # Add metadata header
    import datetime as dt
    meta = {
        'exported_at': dt.datetime.now().isoformat(),
        'from_date': from_date,
        'to_date': to_date,
        'sections': list(data.keys()),
        'total_records': sum(len(v) for v in data.values()),
        'app': 'MediScan Health OS'
    }

    fname_base = f"mediscan_{from_date}_to_{to_date}"

    if fmt == 'csv':
        output = io.StringIO()
        # Write metadata as comments
        output.write("# MediScan Health OS Export\n")
        output.write('# Exported: ' + meta['exported_at'] + '\n')
        output.write('# Period: ' + from_date + ' to ' + to_date + '\n\n')
        for section, rows in data.items():
            if not rows: continue
            output.write('# === ' + section.upper().replace('_',' ') + ' (' + str(len(rows)) + ' records) ===\n')
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            output.write('\n')
        csv_data = output.getvalue()
        from flask import Response
        return Response(csv_data, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={fname_base}.csv'})
    else:
        from flask import Response
        import json as json_mod
        export_obj = {'_meta': meta, **data}
        return Response(json_mod.dumps(export_obj, indent=2, default=str),
                        mimetype='application/json',
                        headers={'Content-Disposition': f'attachment; filename={fname_base}.json'})


# ══════════════════════════════════════════════════════════════════════════════
# Hydration Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/hydration/<date_key>')
def api_hydration_day(date_key):
    data = get_hydration_day(date_key)
    profile = get_profile()
    goal_ml = round(float(profile.get('weight_kg', 70)) * 35)
    data['goal_ml'] = goal_ml
    data['pct'] = min(round(data['total_ml'] / goal_ml * 100), 100) if goal_ml else 0
    return jsonify(data)

@bp.route('/api/hydration', methods=['POST'])
def api_log_hydration():
    data = request.json or {}
    log = log_hydration(int(data.get('amount_ml', 250)), data.get('drink_type','water'),
                        data.get('date_key', today_iso()))
    return jsonify({'success': True, 'log': log})

@bp.route('/api/hydration/<lid>', methods=['DELETE'])
def api_del_hydration(lid):
    delete_hydration_log(lid)
    return jsonify({'success': True})

@bp.route('/api/hydration/week')
def api_hydration_week():
    profile = get_profile()
    goal_ml = round(float(profile.get('weight_kg', 70)) * 35)
    week = get_hydration_week(7)
    for d in week: d['goal_ml'] = goal_ml
    return jsonify(week)

# ══════════════════════════════════════════════════════════════════════════════
# Sleep Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/sleep')
def api_get_sleep():
    days = int(request.args.get('days', 14))
    return jsonify(get_sleep_logs(days))

@bp.route('/api/sleep', methods=['POST'])
def api_log_sleep():
    data = request.json or {}
    if not data.get('bedtime') or not data.get('wake_time'):
        return jsonify({'success': False, 'error': 'bedtime and wake_time required'}), 400
    # Calculate duration
    import datetime as dt
    try:
        bed  = dt.datetime.fromisoformat(data['bedtime'])
        wake = dt.datetime.fromisoformat(data['wake_time'])
        if wake < bed: wake += dt.timedelta(days=1)
        dur = round((wake - bed).total_seconds() / 3600, 2)
        data['duration_h'] = dur
        data.setdefault('date_key', wake.date().isoformat())
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid datetime format'}), 400
    s = log_sleep(data)
    return jsonify({'success': True, 'sleep': s})

@bp.route('/api/sleep/<lid>', methods=['DELETE'])
def api_del_sleep(lid):
    delete_sleep_log(lid)
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════════════════
# Body Metrics Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/body-metrics')
def api_get_body_metrics():
    days = int(request.args.get('days', 30))
    return jsonify(get_body_metrics(days))

@bp.route('/api/body-metrics', methods=['POST'])
def api_log_body_metric():
    data = request.json or {}
    data.setdefault('date_key', today_iso())
    profile = get_profile()
    data.setdefault('height_cm', profile.get('height_cm', 170))
    m = log_body_metric(data)
    return jsonify({'success': True, 'metric': m})

# ══════════════════════════════════════════════════════════════════════════════
# Habits Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/habits')
def api_get_habits():
    return jsonify(get_habit_stats())

@bp.route('/api/habits', methods=['POST'])
def api_create_habit():
    data = request.json or {}
    if not data.get('name','').strip():
        return jsonify({'success': False, 'error': 'Name required'}), 400
    h = create_habit(data)
    return jsonify({'success': True, 'habit': h})

@bp.route('/api/habits/<hid>', methods=['DELETE'])
def api_delete_habit(hid):
    delete_habit(hid)
    return jsonify({'success': True})

@bp.route('/api/habits/<hid>/toggle', methods=['POST'])
def api_toggle_habit(hid):
    date_key = (request.json or {}).get('date_key', today_iso())
    result = toggle_habit_log(hid, date_key)
    return jsonify({'success': True, **result})

# ══════════════════════════════════════════════════════════════════════════════
# Symptoms Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/symptoms')
def api_get_symptoms():
    days = int(request.args.get('days', 14))
    return jsonify(get_symptoms(days))

@bp.route('/api/symptoms', methods=['POST'])
def api_log_symptom():
    data = request.json or {}
    if not data.get('name','').strip():
        return jsonify({'success': False, 'error': 'Symptom name required'}), 400
    s = log_symptom(data)
    return jsonify({'success': True, 'symptom': s})

@bp.route('/api/symptoms/<sid>', methods=['DELETE'])
def api_del_symptom(sid):
    delete_symptom(sid)
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════════════════
# Vitals Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/vitals')
def api_get_vitals():
    vtype = request.args.get('type')
    days  = int(request.args.get('days', 30))
    return jsonify(get_vitals(vtype, days))

@bp.route('/api/vitals', methods=['POST'])
def api_log_vital():
    data = request.json or {}
    if not data.get('type') or data.get('value1') is None:
        return jsonify({'success': False, 'error': 'type and value1 required'}), 400
    v = log_vital(data)
    return jsonify({'success': True, 'vital': v})

@bp.route('/api/vitals/<vid>', methods=['DELETE'])
def api_del_vital(vid):
    delete_vital(vid)
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════════════════════
# Emergency Info Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/emergency')
def api_get_emergency():
    return jsonify(get_emergency_info())

@bp.route('/api/emergency', methods=['POST'])
def api_save_emergency():
    data = request.json or {}
    info = save_emergency_info(data)
    return jsonify({'success': True, 'info': info})

# ══════════════════════════════════════════════════════════════════════════════
# Unified wellness summary (for dashboard sync)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/wellness/today')
def api_wellness_today():
    day = today_iso()
    hydration = get_hydration_day(day)
    profile   = get_profile()
    goal_ml   = round(float(profile.get('weight_kg', 70)) * 35)
    sleeps    = get_sleep_logs(1)
    habits    = get_habit_stats()
    symptoms  = get_symptoms(1)
    return jsonify({
        'hydration': {'total_ml': hydration['total_ml'], 'goal_ml': goal_ml,
                      'pct': min(round(hydration['total_ml']/goal_ml*100),100) if goal_ml else 0},
        'sleep':     sleeps[0] if sleeps and sleeps[0].get('date_key') == day else None,
        'habits':    {'total': len(habits['habits']),
                      'done': sum(1 for h in habits['habits'] if h['done_today'])},
        'symptoms':  [s for s in symptoms if s['date_key'] == day],
    })

# ══════════════════════════════════════════════════════════════════════════════
# Thoughts (Daily Journal) Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/thoughts/<date_key>')
def api_get_thoughts(date_key):
    thoughts = get_thoughts(date_key)
    count = len(thoughts)
    return jsonify({
        'thoughts': thoughts,
        'count': count,
        'remaining': max(0, MAX_THOUGHTS_PER_DAY - count),
        'limit': MAX_THOUGHTS_PER_DAY,
        'date': date_key
    })

@bp.route('/api/thoughts', methods=['POST'])
def api_save_thought():
    data = request.json or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'Content required'}), 400
    if len(content) > 1000:
        return jsonify({'success': False, 'error': 'Max 1000 characters'}), 400
    date_key = data.get('date_key', today_iso())
    mood = data.get('mood', 'neutral')
    try:
        thought = save_thought(content, mood, date_key)
        return jsonify({'success': True, 'thought': thought,
                        'remaining': max(0, MAX_THOUGHTS_PER_DAY - count_thoughts_today(date_key))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 429

@bp.route('/api/thoughts/<tid>', methods=['PUT'])
def api_update_thought(tid):
    data = request.json or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'error': 'Content required'}), 400
    t = update_thought(tid, content, data.get('mood', 'neutral'))
    return jsonify({'success': True, 'thought': t})

@bp.route('/api/thoughts/<tid>', methods=['DELETE'])
def api_delete_thought(tid):
    delete_thought(tid)
    return jsonify({'success': True})

@bp.route('/api/thoughts/range/week')
def api_thoughts_week():
    return jsonify(get_thoughts_range(7))

# ══════════════════════════════════════════════════════════════════════════════
# Todos Routes
# ══════════════════════════════════════════════════════════════════════════════

@bp.route('/api/todos')
def api_list_todos():
    status = request.args.get('status')
    todos = list_todos(status)
    pending = [t for t in todos if t['status'] == 'pending']
    done    = [t for t in todos if t['status'] == 'done']
    return jsonify({'todos': todos, 'pending_count': len(pending), 'done_count': len(done)})

@bp.route('/api/todos', methods=['POST'])
def api_create_todo():
    data = request.json or {}
    if not data.get('title', '').strip():
        return jsonify({'success': False, 'error': 'Title required'}), 400
    todo = create_todo(data)
    return jsonify({'success': True, 'todo': todo})

@bp.route('/api/todos/<tid>', methods=['PUT'])
def api_update_todo(tid):
    data = request.json or {}
    todo = update_todo(tid, data)
    return jsonify({'success': True, 'todo': todo})

@bp.route('/api/todos/<tid>/toggle', methods=['POST'])
def api_toggle_todo(tid):
    todo = toggle_todo(tid)
    return jsonify({'success': True, 'todo': todo})

@bp.route('/api/todos/<tid>', methods=['DELETE'])
def api_delete_todo(tid):
    delete_todo(tid)
    return jsonify({'success': True})

@bp.route('/api/todos/reminders/due')
def api_due_reminders():
    reminders = get_due_reminders()
    for r in reminders:
        mark_reminder_sent(r['id'])
    return jsonify({'reminders': reminders})

# ══════════════════════════════════════════════════════════════════════════════
# Startup
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    init_db()
    from scheduler import start_scheduler
    start_scheduler()
    app.run(debug=True, port=5000, use_reloader=False)

