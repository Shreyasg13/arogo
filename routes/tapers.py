"""routes/tapers.py — medication tapering schedules.

GET    /api/tapers                    — overview (meds that have a taper)
GET    /api/tapers/<medicine_id>      — the full step schedule for one med
POST   /api/tapers                    — {medicine_id, dosage, start_date, note}
DELETE /api/tapers/step/<id>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.tapers import add_step, delete_step, get_taper, list_tapers

bp = Blueprint('tapers', __name__)


@bp.route('/api/tapers')
@require_auth
def api_list():
    return jsonify({'tapers': list_tapers()})


@bp.route('/api/tapers/<medicine_id>')
@require_auth
def api_get(medicine_id):
    return jsonify(get_taper(medicine_id))


@bp.route('/api/tapers', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'step': add_step(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/tapers/step/<sid>', methods=['DELETE'])
@require_auth
def api_delete(sid):
    delete_step(sid)
    return jsonify({'success': True})
