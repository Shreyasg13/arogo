"""routes/insurance.py — health-insurance policies and renewal countdowns."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.insurance import (create_policy, update_policy, delete_policy,
                          list_policies, KINDS, PERIODS)

bp = Blueprint('insurance', __name__)


@bp.route('/api/insurance')
@require_auth
def api_list():
    d = list_policies()
    return jsonify({**d, 'kinds': list(KINDS), 'periods': list(PERIODS)})


@bp.route('/api/insurance', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'policy': create_policy(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/insurance/<pid>', methods=['PATCH'])
@require_auth
def api_update(pid):
    try:
        return jsonify({'success': True, 'policy': update_policy(pid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404


@bp.route('/api/insurance/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    delete_policy(pid)
    return jsonify({'success': True})
