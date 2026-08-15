"""routes/quit.py — O2 quit tracker. All @require_auth, user-scoped; every
figure is arithmetic on the user's own inputs."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.quit import add_plan, update_plan, list_plans, delete_plan, KINDS

bp = Blueprint('quit', __name__)


@bp.route('/api/quit')
@require_auth
def api_list():
    return jsonify({'plans': list_plans(), 'kinds': list(KINDS)})


@bp.route('/api/quit', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'plan': add_plan(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/quit/<pid>', methods=['PATCH'])
@require_auth
def api_update(pid):
    try:
        p = update_plan(pid, request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not p:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'plan': p})


@bp.route('/api/quit/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    delete_plan(pid)
    return jsonify({'success': True})
