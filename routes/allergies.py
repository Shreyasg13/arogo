"""routes/allergies.py — structured allergy & reactions log.

GET    /api/allergies          — list (most severe first)
POST   /api/allergies          — {allergen, reaction, severity, date_noted, notes}
PATCH  /api/allergies/<id>
DELETE /api/allergies/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.allergies import create_allergy, update_allergy, delete_allergy, list_allergies, SEVERITIES

bp = Blueprint('allergies', __name__)


@bp.route('/api/allergies')
@require_auth
def api_list():
    return jsonify({'allergies': list_allergies(), 'severities': list(SEVERITIES)})


@bp.route('/api/allergies', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'allergy': create_allergy(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/allergies/<aid>', methods=['PATCH'])
@require_auth
def api_update(aid):
    try:
        return jsonify({'success': True, 'allergy': update_allergy(aid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/allergies/<aid>', methods=['DELETE'])
@require_auth
def api_delete(aid):
    delete_allergy(aid)
    return jsonify({'success': True})
