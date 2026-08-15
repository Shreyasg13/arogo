"""routes/family_history.py — N3 family medical history.

A plain record of relatives' conditions, for the question every new doctor asks.
All @require_auth and user-scoped; facts only, never interpreted.

GET    /api/family-history            — the user's entries
POST   /api/family-history            — {relation, condition, age_at_onset, notes}
DELETE /api/family-history/<eid>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.family_history import add_entry, list_entries, delete_entry, RELATIONS

bp = Blueprint('family_history', __name__)


@bp.route('/api/family-history')
@require_auth
def api_list():
    return jsonify({'entries': list_entries(), 'relations': list(RELATIONS)})


@bp.route('/api/family-history', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'entry': add_entry(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/family-history/<eid>', methods=['DELETE'])
@require_auth
def api_delete(eid):
    delete_entry(eid)
    return jsonify({'success': True})
