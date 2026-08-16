"""routes/health_reminders.py — D custom health reminders. All @require_auth,
user-scoped. The user defines every reminder; the app recommends nothing.

GET    /api/health-reminders
POST   /api/health-reminders            — {title, due_date, repeat_days, notes}
POST   /api/health-reminders/<rid>/done — tick (rolls a repeat forward)
DELETE /api/health-reminders/<rid>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.health_reminders import add_reminder, list_reminders, complete_reminder, delete_reminder

bp = Blueprint('health_reminders', __name__)


@bp.route('/api/health-reminders')
@require_auth
def api_list():
    return jsonify({'reminders': list_reminders()})


@bp.route('/api/health-reminders', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'reminder': add_reminder(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/health-reminders/<rid>/done', methods=['POST'])
@require_auth
def api_done(rid):
    r = complete_reminder(rid)
    if not r:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'reminder': r})


@bp.route('/api/health-reminders/<rid>', methods=['DELETE'])
@require_auth
def api_delete(rid):
    delete_reminder(rid)
    return jsonify({'success': True})
