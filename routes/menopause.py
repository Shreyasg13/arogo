"""routes/menopause.py — O3 menopause companion. All @require_auth, user-scoped,
descriptive only."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.menopause import add_log, list_logs, get_summary, delete_log, SYMPTOMS

bp = Blueprint('menopause', __name__)


@bp.route('/api/menopause')
@require_auth
def api_list():
    return jsonify({'logs': list_logs(), 'summary': get_summary(), 'symptoms': list(SYMPTOMS)})


@bp.route('/api/menopause', methods=['POST'])
@require_auth
def api_add():
    return jsonify({'success': True, 'log': add_log(request.json or {})})


@bp.route('/api/menopause/<lid>', methods=['DELETE'])
@require_auth
def api_delete(lid):
    delete_log(lid)
    return jsonify({'success': True})
