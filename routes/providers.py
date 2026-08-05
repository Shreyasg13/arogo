"""routes/providers.py — "My care team" provider directory.

GET    /api/providers            — list the user's providers
POST   /api/providers            — {name, specialty, phone, clinic, address, notes}
PATCH  /api/providers/<id>       — any of the above
DELETE /api/providers/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.providers import create_provider, update_provider, delete_provider, list_providers

bp = Blueprint('providers', __name__)


@bp.route('/api/providers')
@require_auth
def api_list():
    return jsonify({'providers': list_providers()})


@bp.route('/api/providers', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'provider': create_provider(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/providers/<pid>', methods=['PATCH'])
@require_auth
def api_update(pid):
    try:
        return jsonify({'success': True, 'provider': update_provider(pid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/providers/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    delete_provider(pid)
    return jsonify({'success': True})
