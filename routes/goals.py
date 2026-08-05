"""routes/goals.py — outcome health goals.

GET    /api/goals[?all=1]     — active goals (or all), + metric catalog
POST   /api/goals             — {metric, target_value, direction, deadline, title}
PATCH  /api/goals/<id>        — {status: active|achieved|archived}
DELETE /api/goals/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.goals import create_goal, update_goal, delete_goal, list_goals

bp = Blueprint('goals', __name__)


@bp.route('/api/goals')
@require_auth
def api_list():
    include = request.args.get('all') in ('1', 'true', 'yes')
    return jsonify(list_goals(include_done=include))


@bp.route('/api/goals', methods=['POST'])
@require_auth
def api_create():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'goal': create_goal(
            d.get('metric', ''), d.get('target_value'),
            d.get('direction'), d.get('deadline'), d.get('title', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/goals/<gid>', methods=['PATCH'])
@require_auth
def api_update(gid):
    try:
        return jsonify({'success': True, 'goal': update_goal(gid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/goals/<gid>', methods=['DELETE'])
@require_auth
def api_delete(gid):
    delete_goal(gid)
    return jsonify({'success': True})
