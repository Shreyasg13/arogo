"""routes/claims.py — insurance-claims tracker.

GET    /api/claims            — list + summary + status vocab
POST   /api/claims            — {insurer, amount, date_submitted, status, reimbursed, notes}
PATCH  /api/claims/<id>
DELETE /api/claims/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.claims import create_claim, update_claim, delete_claim, list_claims

bp = Blueprint('claims', __name__)


@bp.route('/api/claims')
@require_auth
def api_list():
    return jsonify(list_claims())


@bp.route('/api/claims', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'claim': create_claim(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/claims/<cid>', methods=['PATCH'])
@require_auth
def api_update(cid):
    try:
        return jsonify({'success': True, 'claim': update_claim(cid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/claims/<cid>', methods=['DELETE'])
@require_auth
def api_delete(cid):
    delete_claim(cid)
    return jsonify({'success': True})
