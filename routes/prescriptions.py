"""routes/prescriptions.py — the prescription library.

GET    /api/prescriptions          — list + attention count
POST   /api/prescriptions          — {prescriber, date_issued, valid_until, refills_left, medicine_ids, notes}
PATCH  /api/prescriptions/<id>
DELETE /api/prescriptions/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.prescriptions import (create_prescription, update_prescription,
                              delete_prescription, list_prescriptions)

bp = Blueprint('prescriptions', __name__)


@bp.route('/api/prescriptions')
@require_auth
def api_list():
    return jsonify(list_prescriptions())


@bp.route('/api/prescriptions', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'prescription': create_prescription(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/prescriptions/<pid>', methods=['PATCH'])
@require_auth
def api_update(pid):
    try:
        return jsonify({'success': True, 'prescription': update_prescription(pid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/prescriptions/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    delete_prescription(pid)
    return jsonify({'success': True})
