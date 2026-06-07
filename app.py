"""
app.py — MediScan Health OS.

Usage:
    python app.py
"""
import os
from flask import Flask, render_template, send_from_directory
from config import Config

# ── Import database layer at module level so all functions are available ──────
try:
    from db.core import init_db
    from db import (
        execute, today_iso,
        insert_report, list_reports, get_report, delete_report, report_stats,
        insert_medicine, list_medicines, get_medicine, toggle_medicine, delete_medicine,
        log_dose, get_today_doses, get_adherence_stats,
        update_medicine_stock, get_low_stock_medicines,
        insert_activity, list_activities, delete_activity, fitness_stats,
        get_token, list_tokens, delete_token, get_sync_history,
        get_profile, update_profile, calc_tdee,
        log_food, get_food_logs, delete_food_log, get_nutrition_summary, get_weekly_nutrition,
        save_custom_food, list_custom_foods,
        get_thoughts, save_thought, update_thought, delete_thought,
        get_thoughts_range, count_thoughts_today, MAX_THOUGHTS_PER_DAY,
        list_todos, create_todo, update_todo, toggle_todo, delete_todo,
        get_due_reminders, mark_reminder_sent,
        log_hydration, get_hydration_day, delete_hydration_log, get_hydration_week,
        log_sleep, get_sleep_logs, delete_sleep_log,
        log_body_metric, get_body_metrics,
        list_habits, create_habit, delete_habit, toggle_habit_log, get_habit_stats,
        log_symptom, get_symptoms, delete_symptom,
        log_vital, get_vitals, delete_vital,
        get_emergency_info, save_emergency_info,
        add_notification, get_notifications, mark_notification_read,
        mark_all_notifications_read, unread_notification_count,
        generate_weekly_report, global_search, get_goal_progress,
    )
    _DB_SOURCE = "db package"
except ImportError:
    from database import *
    from database import execute, today_iso
    _DB_SOURCE = "database.py"


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)
    app.config['UPLOAD_FOLDER']      = config.UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

    # ── Try blueprint-based routing first, fall back to inline routes ─────────
    try:
        from routes.reports   import bp as reports_bp
        from routes.medicines import bp as medicines_bp
        from routes.fitness   import bp as fitness_bp
        from routes.oauth     import bp as oauth_bp
        from routes.food      import bp as food_bp
        from routes.wellness  import bp as wellness_bp
        from routes.insights  import bp as insights_bp

        app.register_blueprint(reports_bp)
        app.register_blueprint(medicines_bp)
        app.register_blueprint(fitness_bp)
        app.register_blueprint(oauth_bp)
        app.register_blueprint(food_bp)
        app.register_blueprint(wellness_bp)
        app.register_blueprint(insights_bp)

    except ImportError:
        # routes/ package not present — register all routes inline from
        # the original monolithic app logic already in database.py/app.py
        _register_inline_routes(app)

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/uploads/<filename>')
    def uploaded_file(filename):
        return send_from_directory(config.UPLOAD_FOLDER, filename)

    return app


def _register_inline_routes(app):
    """Inline route registration — used when routes/ package is absent."""
    from flask import request, jsonify
    import json as _json

    # ── Stats ──────────────────────────────────────────────────────────────────
    @app.route('/api/stats')
    def api_stats():
        return jsonify(report_stats())

    # ── Reports ────────────────────────────────────────────────────────────────
    @app.route('/api/reports')
    def api_reports():
        return jsonify(list_reports())

    @app.route('/api/reports/<rid>', methods=['DELETE'])
    def api_del_report(rid):
        delete_report(rid)
        return jsonify({'success': True})

    @app.route('/api/upload', methods=['POST'])
    def api_upload():
        from werkzeug.utils import secure_filename
        import uuid, datetime
        f = request.files.get('file')
        if not f:
            return jsonify({'success': False, 'error': 'No file'}), 400
        ext  = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        fname = uuid.uuid4().hex + ('.' + ext if ext else '')
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        data = {k: request.form.get(k, '') for k in
                ['patient_name','report_type','report_date','tags','analysis_notes','severity','doctor']}
        data['tags'] = _json.dumps([t.strip() for t in data['tags'].split(',') if t.strip()])
        rep = insert_report(fname, f.filename, ext, data)
        return jsonify({'success': True, 'report': rep})

    # ── Medicines ──────────────────────────────────────────────────────────────
    @app.route('/api/medicines')
    def api_medicines():
        return jsonify(list_medicines())

    @app.route('/api/medicines', methods=['POST'])
    def api_add_medicine():
        med = insert_medicine(request.json or {})
        return jsonify({'success': True, 'medicine': med})

    @app.route('/api/medicines/<mid>', methods=['DELETE'])
    def api_del_medicine(mid):
        delete_medicine(mid)
        return jsonify({'success': True})

    @app.route('/api/medicines/<mid>/toggle', methods=['POST'])
    def api_toggle_medicine(mid):
        toggle_medicine(mid)
        return jsonify({'success': True})

    @app.route('/api/medicines/today')
    def api_today_doses():
        return jsonify(get_today_doses())

    @app.route('/api/medicines/<mid>/log', methods=['POST'])
    def api_log_dose(mid):
        d = request.json or {}
        log_dose(mid, d.get('scheduled',''), d.get('taken', True))
        return jsonify({'success': True})

    @app.route('/api/medicines/<mid>/stock', methods=['POST'])
    def api_update_stock(mid):
        d = request.json or {}
        update_medicine_stock(mid, int(d.get('pill_count',0)),
                              int(d.get('pills_per_dose',1)),
                              int(d.get('refill_threshold',7)))
        return jsonify({'success': True})

    @app.route('/api/medicines/low-stock')
    def api_low_stock():
        return jsonify(get_low_stock_medicines())

    @app.route('/api/medicines/adherence')
    def api_med_adherence():
        return jsonify({'medicines': list_medicines()})

    # ── Fitness ────────────────────────────────────────────────────────────────
    @app.route('/api/fitness/stats')
    def api_fitness_stats():
        return jsonify(fitness_stats())

    @app.route('/api/fitness/activities')
    def api_list_activities():
        return jsonify(list_activities())

    @app.route('/api/fitness/activities', methods=['POST'])
    def api_add_activity():
        act = insert_activity(request.json or {})
        return jsonify({'success': True, 'activity': act})

    @app.route('/api/fitness/activities/<aid>', methods=['DELETE'])
    def api_del_activity(aid):
        delete_activity(aid)
        return jsonify({'success': True})

    @app.route('/api/fitness/calendar')
    def api_fitness_calendar():
        return jsonify(list_activities())

    @app.route('/api/fitness/consistency')
    def api_fitness_consistency():
        return jsonify(list_activities())

    @app.route('/api/fitness/connected')
    def api_fitness_connected():
        return jsonify(list_tokens())

    @app.route('/api/fitness/sync', methods=['POST'])
    def api_fitness_sync():
        return jsonify({'success': True, 'synced': 0})

    @app.route('/api/fitness/sync-log')
    def api_sync_log():
        return jsonify(get_sync_history())

    @app.route('/api/fitness/service-status')
    def api_service_status():
        return jsonify({})

    @app.route('/api/fitness/disconnect', methods=['POST'])
    def api_disconnect():
        d = request.json or {}
        delete_token(d.get('service',''))
        return jsonify({'success': True})

    @app.route('/api/fitness/apple/import', methods=['POST'])
    def api_apple_import():
        return jsonify({'success': True, 'imported': 0})

    # ── Food ───────────────────────────────────────────────────────────────────
    @app.route('/api/food/profile')
    def api_food_profile():
        p = get_profile()
        return jsonify({'profile': p, 'targets': calc_tdee(p)})

    @app.route('/api/food/profile', methods=['POST'])
    def api_save_profile():
        p = update_profile(request.json or {})
        return jsonify({'success': True, 'profile': p, 'targets': calc_tdee(p)})

    @app.route('/api/food/log/<date_key>')
    def api_food_log(date_key):
        p = get_profile()
        return jsonify({'logs': get_food_logs(date_key), 'summary': get_nutrition_summary(date_key),
                        'targets': calc_tdee(p)})

    @app.route('/api/food/log', methods=['POST'])
    def api_add_food():
        entry = log_food(request.json or {})
        return jsonify({'success': True, 'entry': entry})

    @app.route('/api/food/log/<lid>', methods=['DELETE'])
    def api_del_food(lid):
        delete_food_log(lid)
        return jsonify({'success': True})

    @app.route('/api/food/weekly')
    def api_food_weekly():
        return jsonify(get_weekly_nutrition())

    @app.route('/api/food/db')
    def api_food_db():
        try:
            from food_data import search_food, CATEGORIES
        except ImportError:
            import importlib.util as _ilu, os as _os
            _path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'food_data.py')
            _spec = _ilu.spec_from_file_location('food_data', _path)
            _mod  = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            search_food = _mod.search_food
            CATEGORIES  = _mod.CATEGORIES
        q   = request.args.get('q','')
        cat = request.args.get('category','')
        std = search_food(query=q, category=cat)
        # Merge in saved custom foods so they appear in search results
        custom = list_custom_foods()
        if q:
            ql = q.lower()
            custom = [c for c in custom if ql in c['name'].lower()]
        # Tag custom foods so the UI can show a badge
        for c in custom:
            c['is_custom'] = True
            c.setdefault('emoji', '⭐')
            c.setdefault('category', 'My Foods')
        foods = custom + std          # custom foods shown first
        return jsonify({'foods': foods, 'categories': CATEGORIES,
                        'custom_count': len(list_custom_foods())})

    @app.route('/api/food/custom', methods=['POST'])
    def api_save_custom():
        d = request.json or {}
        if not d.get('name'):
            return jsonify({'success': False, 'error': 'Name required'}), 400
        food = save_custom_food(d)
        return jsonify({'success': True, 'food': food})

    @app.route('/api/food/custom')
    def api_list_custom():
        return jsonify(list_custom_foods())

    @app.route('/api/food/custom/<fid>', methods=['DELETE'])
    def api_del_custom(fid):
        execute("DELETE FROM custom_foods WHERE id=?", (fid,), commit=True)
        return jsonify({'success': True})

    # ── Wellness ───────────────────────────────────────────────────────────────
    @app.route('/api/wellness/today')
    def api_wellness_today():
        today = today_iso()
        hyd   = get_hydration_day(today)
        sl    = get_sleep_logs(1)
        hab   = get_habit_stats(1)
        sym   = get_symptoms(1)
        return jsonify({
            'hydration': hyd,
            'sleep':     sl[0] if sl else None,
            'habits':    {'done': sum(1 for h in hab['habits'] if today in h['done_dates']),
                          'total': len(hab['habits'])},
            'symptoms':  len([s for s in sym if s['date_key'] == today])
        })

    @app.route('/api/thoughts/<date_key>')
    def api_get_thoughts(date_key):
        return jsonify(get_thoughts(date_key))

    @app.route('/api/thoughts', methods=['POST'])
    def api_save_thought():
        t = save_thought(request.json or {})
        return jsonify({'success': True, 'thought': t})

    @app.route('/api/thoughts/<tid>', methods=['PUT'])
    def api_update_thought(tid):
        t = update_thought(tid, request.json or {})
        return jsonify({'success': True, 'thought': t})

    @app.route('/api/thoughts/<tid>', methods=['DELETE'])
    def api_del_thought(tid):
        delete_thought(tid)
        return jsonify({'success': True})

    @app.route('/api/thoughts/range/week')
    def api_thoughts_week():
        return jsonify(get_thoughts_range(7))

    @app.route('/api/thoughts')
    def api_thoughts_list():
        return jsonify(get_thoughts_range(30))

    @app.route('/api/todos')
    def api_todos():
        return jsonify({'todos': list_todos()})

    @app.route('/api/todos', methods=['POST'])
    def api_create_todo():
        t = create_todo(request.json or {})
        return jsonify({'success': True, 'todo': t})

    @app.route('/api/todos/<tid>', methods=['PUT'])
    def api_update_todo(tid):
        t = update_todo(tid, request.json or {})
        return jsonify({'success': True, 'todo': t})

    @app.route('/api/todos/<tid>', methods=['DELETE'])
    def api_del_todo(tid):
        delete_todo(tid)
        return jsonify({'success': True})

    @app.route('/api/todos/<tid>/toggle', methods=['POST'])
    def api_toggle_todo(tid):
        toggle_todo(tid)
        return jsonify({'success': True})

    @app.route('/api/todos/reminders/due')
    def api_due_reminders():
        return jsonify(get_due_reminders())

    @app.route('/api/hydration/<date_key>')
    def api_hydration_day(date_key):
        return jsonify(get_hydration_day(date_key))

    @app.route('/api/hydration/week')
    def api_hydration_week():
        return jsonify(get_hydration_week())

    @app.route('/api/hydration', methods=['POST'])
    def api_log_hydration():
        d = request.json or {}
        log_hydration(d.get('amount_ml', 250),
                      d.get('drink_type', 'water'),
                      d.get('date_key', today_iso()))
        return jsonify({'success': True})

    @app.route('/api/hydration/<lid>', methods=['DELETE'])
    def api_del_hydration(lid):
        delete_hydration_log(lid)
        return jsonify({'success': True})

    @app.route('/api/sleep')
    def api_sleep():
        days = int(request.args.get('days', 14))
        return jsonify(get_sleep_logs(days))

    @app.route('/api/sleep', methods=['POST'])
    def api_log_sleep():
        s = log_sleep(request.json or {})
        return jsonify({'success': True, 'log': s})

    @app.route('/api/sleep/<lid>', methods=['DELETE'])
    def api_del_sleep(lid):
        delete_sleep_log(lid)
        return jsonify({'success': True})

    @app.route('/api/body-metrics')
    def api_body_metrics():
        return jsonify(get_body_metrics())

    @app.route('/api/body-metrics', methods=['POST'])
    def api_log_body():
        m = log_body_metric(request.json or {})
        return jsonify({'success': True, 'metric': m})

    @app.route('/api/habits')
    def api_habits():
        return jsonify(get_habit_stats())

    @app.route('/api/habits', methods=['POST'])
    def api_create_habit():
        h = create_habit(request.json or {})
        return jsonify({'success': True, 'habit': h})

    @app.route('/api/habits/<hid>', methods=['DELETE'])
    def api_del_habit(hid):
        delete_habit(hid)
        return jsonify({'success': True})

    @app.route('/api/habits/<hid>/toggle', methods=['POST'])
    def api_toggle_habit(hid):
        d = request.json or {}
        toggle_habit_log(hid, d.get('date_key', today_iso()))
        return jsonify({'success': True})

    @app.route('/api/symptoms')
    def api_symptoms():
        days = int(request.args.get('days', 14))
        return jsonify(get_symptoms(days))

    @app.route('/api/symptoms', methods=['POST'])
    def api_log_symptom():
        s = log_symptom(request.json or {})
        return jsonify({'success': True, 'symptom': s})

    @app.route('/api/symptoms/<sid>', methods=['DELETE'])
    def api_del_symptom(sid):
        delete_symptom(sid)
        return jsonify({'success': True})

    @app.route('/api/vitals')
    def api_vitals():
        return jsonify(get_vitals())

    @app.route('/api/vitals', methods=['POST'])
    def api_log_vital():
        v = log_vital(request.json or {})
        return jsonify({'success': True, 'vital': v})

    @app.route('/api/vitals/<vid>', methods=['DELETE'])
    def api_del_vital(vid):
        delete_vital(vid)
        return jsonify({'success': True})

    @app.route('/api/emergency')
    def api_emergency():
        return jsonify(get_emergency_info())

    @app.route('/api/emergency', methods=['POST'])
    def api_save_emergency():
        save_emergency_info(request.json or {})
        return jsonify({'success': True})

    # ── Insights ───────────────────────────────────────────────────────────────
    @app.route('/api/notifications')
    def api_notifications():
        limit = int(request.args.get('limit', 50))
        notes = get_notifications(limit)
        return jsonify({'notifications': notes, 'unread': unread_notification_count()})

    @app.route('/api/notifications', methods=['POST'])
    def api_add_notif():
        d = request.json or {}
        n = add_notification(d.get('type','system'), d.get('title',''), d.get('body',''))
        return jsonify({'success': True, 'notification': n})

    @app.route('/api/notifications/<nid>/read', methods=['POST'])
    def api_notif_read(nid):
        mark_notification_read(nid)
        return jsonify({'success': True, 'unread': unread_notification_count()})

    @app.route('/api/notifications/read-all', methods=['POST'])
    def api_notif_read_all():
        mark_all_notifications_read()
        return jsonify({'success': True})

    @app.route('/api/report/weekly')
    def api_weekly_report():
        return jsonify(generate_weekly_report())

    @app.route('/api/progress')
    def api_progress():
        return jsonify(get_goal_progress())

    @app.route('/api/search')
    def api_search():
        q = request.args.get('q','').strip()
        if len(q) < 2:
            return jsonify({'query': q, 'total': 0, 'sections': []})
        return jsonify(global_search(q))

    @app.route('/api/export/counts')
    def api_export_counts():
        from_d = request.args.get('from', '2000-01-01')
        to_d   = request.args.get('to',   today_iso())
        counts = {
            'food_logs':          execute("SELECT COUNT(*) as n FROM food_logs WHERE date_key BETWEEN ? AND ?",       (from_d,to_d), fetchone=True)['n'],
            'fitness_activities': execute("SELECT COUNT(*) as n FROM fitness_activities WHERE date BETWEEN ? AND ?",  (from_d,to_d), fetchone=True)['n'],
            'sleep_logs':         execute("SELECT COUNT(*) as n FROM sleep_logs WHERE date_key BETWEEN ? AND ?",      (from_d,to_d), fetchone=True)['n'],
            'symptoms':           execute("SELECT COUNT(*) as n FROM symptoms WHERE date_key BETWEEN ? AND ?",        (from_d,to_d), fetchone=True)['n'],
            'vitals':             execute("SELECT COUNT(*) as n FROM vitals WHERE date_key BETWEEN ? AND ?",          (from_d,to_d), fetchone=True)['n'],
            'thoughts':           execute("SELECT COUNT(*) as n FROM thoughts WHERE date_key BETWEEN ? AND ?",        (from_d,to_d), fetchone=True)['n'],
            'todos':              execute("SELECT COUNT(*) as n FROM todos",                                           fetchone=True)['n'],
            'body_metrics':       execute("SELECT COUNT(*) as n FROM body_metrics WHERE date_key BETWEEN ? AND ?",    (from_d,to_d), fetchone=True)['n'],
            'hydration_logs':     execute("SELECT COUNT(*) as n FROM hydration_logs WHERE date_key BETWEEN ? AND ?",  (from_d,to_d), fetchone=True)['n'],
            'habits':             execute("SELECT COUNT(*) as n FROM habits WHERE active=1",                           fetchone=True)['n'],
            'medicines':          execute("SELECT COUNT(*) as n FROM medicines WHERE active=1",                        fetchone=True)['n'],
        }
        return jsonify(counts)

    @app.route('/api/export')
    def api_export():
        import csv, io
        fmt      = request.args.get('format', 'json')
        sections = request.args.get('sections', 'all')
        from_d   = request.args.get('from', '2000-01-01')
        to_d     = request.args.get('to', today_iso())
        wanted   = sections.split(',') if sections != 'all' else None
        def want(k): return wanted is None or k in wanted

        data = {}
        if want('food_logs'):
            data['food_logs'] = [dict(r) for r in (execute("SELECT * FROM food_logs WHERE date_key BETWEEN ? AND ? ORDER BY date_key DESC",(from_d,to_d),fetchall=True) or [])]
        if want('fitness_activities'):
            data['fitness_activities'] = list_activities()
        if want('sleep_logs'):
            data['sleep_logs'] = get_sleep_logs(3650)
        if want('symptoms'):
            data['symptoms'] = get_symptoms(3650)
        if want('thoughts'):
            data['thoughts'] = get_thoughts_range(3650)
        if want('todos'):
            data['todos'] = list_todos()
        if want('body_metrics'):
            data['body_metrics'] = get_body_metrics(3650)

        import datetime as _dt
        meta = {'exported_at': _dt.datetime.now().isoformat(), 'from': from_d, 'to': to_d,
                'sections': list(data.keys()), 'app': 'MediScan Health OS'}

        fname = f"mediscan_{from_d}_to_{to_d}"
        if fmt == 'csv':
            output = io.StringIO()
            output.write("# MediScan Health OS Export\n")
            for sec, rows in data.items():
                if not rows: continue
                output.write(f"\n# {sec.upper().replace('_',' ')}\n")
                w = csv.DictWriter(output, fieldnames=rows[0].keys())
                w.writeheader(); w.writerows(rows)
            from flask import Response
            return Response(output.getvalue(), mimetype='text/csv',
                            headers={'Content-Disposition': f'attachment; filename={fname}.csv'})
        else:
            from flask import Response
            import json as _j
            return Response(_j.dumps({'_meta': meta, **data}, indent=2, default=str),
                            mimetype='application/json',
                            headers={'Content-Disposition': f'attachment; filename={fname}.json'})

    # ── OAuth stubs (explicit per-service to avoid duplicate endpoint names) ──
    @app.route('/oauth/strava/start')
    def _oauth_strava_start():
        return jsonify({'url': '/oauth/strava/callback?code=stub'})
    @app.route('/oauth/strava/callback')
    def _oauth_strava_cb():
        return render_template('oauth_result.html', service='strava', status='connected')

    @app.route('/oauth/garmin/start')
    def _oauth_garmin_start():
        return jsonify({'url': '/oauth/garmin/callback?code=stub'})
    @app.route('/oauth/garmin/callback')
    def _oauth_garmin_cb():
        return render_template('oauth_result.html', service='garmin', status='connected')

    @app.route('/oauth/google/start')
    def _oauth_google_start():
        return jsonify({'url': '/oauth/google/callback?code=stub'})
    @app.route('/oauth/google/callback')
    def _oauth_google_cb():
        return render_template('oauth_result.html', service='google', status='connected')


if __name__ == '__main__':
    init_db()
    app = create_app()
    app.run(debug=Config.DEBUG, use_reloader=False, host='0.0.0.0', port=5000)