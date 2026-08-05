"""routes/fasting.py — intermittent-fasting window tracker.

GET    /api/fasting            — active fast + recent history + stats + presets
POST   /api/fasting/start      — {target_hours, start_at?, notes?}
POST   /api/fasting/end        — {end_at?}  (ends the active fast)
DELETE /api/fasting/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.fasting import start_fast, end_fast, delete_fast, list_fasts

bp = Blueprint('fasting', __name__)


@bp.route('/api/fasting')
@require_auth
def api_list():
    return jsonify(list_fasts(request.args.get('limit', 30)))


@bp.route('/api/fasting/start', methods=['POST'])
@require_auth
def api_start():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'fast': start_fast(
            d.get('target_hours'), d.get('start_at'), d.get('notes', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/fasting/end', methods=['POST'])
@require_auth
def api_end():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'fast': end_fast(d.get('id'), d.get('end_at'))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/fasting/<fid>', methods=['DELETE'])
@require_auth
def api_delete(fid):
    delete_fast(fid)
    return jsonify({'success': True})
