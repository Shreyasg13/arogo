"""routes/vital_targets.py — personal vital target ranges.

GET    /api/vital-targets          — {vtype: {target_min, target_max}}
POST   /api/vital-targets          — {vtype, target_min, target_max}
DELETE /api/vital-targets/<vtype>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.vital_targets import set_target, clear_target, get_targets, VITAL_TYPES

bp = Blueprint('vital_targets', __name__)


@bp.route('/api/vital-targets')
@require_auth
def api_get():
    return jsonify({'targets': get_targets(), 'types': list(VITAL_TYPES)})


@bp.route('/api/vital-targets', methods=['POST'])
@require_auth
def api_set():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'target': set_target(
            d.get('vtype'), d.get('target_min'), d.get('target_max'))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/vital-targets/<vtype>', methods=['DELETE'])
@require_auth
def api_clear(vtype):
    clear_target(vtype)
    return jsonify({'success': True})
