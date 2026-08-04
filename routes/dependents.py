"""routes/dependents.py — family profiles for people who don't use the app.

GET    /api/dependents                    — my dependents (with record counts)
POST   /api/dependents                    — add {name, relationship, birthdate, notes}
PATCH  /api/dependents/<id>               — edit a profile
DELETE /api/dependents/<id>               — remove a profile + its records
GET    /api/dependents/<id>/records       — a dependent's records, grouped by kind
POST   /api/dependents/<id>/records       — add {kind, label, detail, date_key}
DELETE /api/dependents/records/<rid>      — remove one record
GET    /api/dependents/meta               — relationship + record-kind vocab
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.dependents import (create_dependent, update_dependent, delete_dependent,
                           list_dependents, add_record, delete_record, get_records,
                           RELATIONSHIPS, RECORD_KINDS)

bp = Blueprint('dependents', __name__)


@bp.route('/api/dependents')
@require_auth
def api_list():
    return jsonify({'dependents': list_dependents()})


@bp.route('/api/dependents', methods=['POST'])
@require_auth
def api_create():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'dependent': create_dependent(
            d.get('name', ''), d.get('relationship', 'other'),
            d.get('birthdate'), d.get('notes', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/dependents/<did>', methods=['PATCH'])
@require_auth
def api_update(did):
    try:
        return jsonify({'success': True, 'dependent': update_dependent(did, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/dependents/<did>', methods=['DELETE'])
@require_auth
def api_delete(did):
    delete_dependent(did)
    return jsonify({'success': True})


@bp.route('/api/dependents/<did>/records')
@require_auth
def api_records(did):
    try:
        return jsonify(get_records(did))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@bp.route('/api/dependents/<did>/records', methods=['POST'])
@require_auth
def api_add_record(did):
    d = request.json or {}
    try:
        return jsonify({'success': True, 'record': add_record(
            did, d.get('kind', ''), d.get('label', ''),
            d.get('detail', ''), d.get('date_key', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/dependents/records/<rid>', methods=['DELETE'])
@require_auth
def api_delete_record(rid):
    delete_record(rid)
    return jsonify({'success': True})


@bp.route('/api/dependents/meta')
@require_auth
def api_meta():
    return jsonify({'relationships': RELATIONSHIPS, 'kinds': RECORD_KINDS})
