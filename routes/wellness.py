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

# ── Body metrics ──────────────────────────────────────────────────────────────
@bp.route('/api/body-metrics')
def api_body_metrics():
    return jsonify(get_body_metrics())

@bp.route('/api/body-metrics', methods=['POST'])
def api_log_body():
    m = log_body_metric(request.json or {})
    return jsonify({'success': True, 'metric': m})

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