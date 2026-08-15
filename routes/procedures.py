"""routes/procedures.py — O1 procedures & hospitalizations. All @require_auth,
user-scoped, facts only."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.procedures import add_procedure, list_procedures, delete_procedure, KINDS

bp = Blueprint('procedures', __name__)


@bp.route('/api/procedures')
@require_auth
def api_list():
    return jsonify({'procedures': list_procedures(), 'kinds': list(KINDS)})


@bp.route('/api/procedures', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'procedure': add_procedure(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/procedures/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    delete_procedure(pid)
    return jsonify({'success': True})
