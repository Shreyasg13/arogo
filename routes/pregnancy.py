"""routes/pregnancy.py — O4 pregnancy tracker. All @require_auth, user-scoped.
Tracking only; no medical guidance."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.pregnancy import (get_pregnancy, set_pregnancy, end_pregnancy,
                          add_log, list_logs, delete_log)

bp = Blueprint('pregnancy', __name__)


@bp.route('/api/pregnancy')
@require_auth
def api_get():
    return jsonify({'pregnancy': get_pregnancy(), 'logs': list_logs()})


@bp.route('/api/pregnancy', methods=['POST'])
@require_auth
def api_set():
    try:
        return jsonify({'success': True, 'pregnancy': set_pregnancy(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/pregnancy/end', methods=['POST'])
@require_auth
def api_end():
    end_pregnancy()
    return jsonify({'success': True})


@bp.route('/api/pregnancy/log', methods=['POST'])
@require_auth
def api_add_log():
    try:
        return jsonify({'success': True, 'log': add_log(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/pregnancy/log/<lid>', methods=['DELETE'])
@require_auth
def api_delete_log(lid):
    delete_log(lid)
    return jsonify({'success': True})
