"""routes/health_notes.py — free-form notes attached to a medicine, condition,
doctor, appointment or lab. The user's own words, stored verbatim."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.health_notes import (create_note, update_note, delete_note, list_notes,
                             ENTITY_TYPES, ENTITY_LABEL)

bp = Blueprint('health_notes', __name__)


@bp.route('/api/notes')
@require_auth
def api_list():
    return jsonify({
        'notes': list_notes(entity_type=request.args.get('entity_type'),
                            entity_id=request.args.get('entity_id'),
                            q=request.args.get('q')),
        'types': [{'key': k, 'label': ENTITY_LABEL[k]} for k in ENTITY_TYPES],
    })


@bp.route('/api/notes', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'note': create_note(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/notes/<nid>', methods=['PATCH'])
@require_auth
def api_update(nid):
    try:
        return jsonify({'success': True, 'note': update_note(nid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404


@bp.route('/api/notes/<nid>', methods=['DELETE'])
@require_auth
def api_delete(nid):
    delete_note(nid)
    return jsonify({'success': True})
