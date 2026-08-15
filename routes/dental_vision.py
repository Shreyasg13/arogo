"""routes/dental_vision.py — dental & vision care.

Checkups (dental cleanings, eye exams) with an optional next-due date, and the
user's own glasses/contacts prescription. Everything is a factual record the
user enters; nothing is scheduled, recommended, or interpreted.

GET    /api/dental-vision/visits[?kind=dental|eye]
POST   /api/dental-vision/visits         — {kind, visit_date, provider, summary, next_due}
DELETE /api/dental-vision/visits/<vid>
GET    /api/dental-vision/due            — next checkup dates you recorded, with countdown
GET    /api/dental-vision/rx             — vision prescriptions (newest first)
POST   /api/dental-vision/rx             — {rx_date, kind, right_sph, ..., pd, notes}
DELETE /api/dental-vision/rx/<rid>
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.dental_vision import (add_visit, list_visits, delete_visit, get_due,
                              add_rx, list_rx, delete_rx,
                              VISIT_KINDS, RX_KINDS)

bp = Blueprint('dental_vision', __name__)


@bp.route('/api/dental-vision/visits')
@require_auth
def api_visits():
    kind = request.args.get('kind')
    return jsonify({'visits': list_visits(kind), 'kinds': list(VISIT_KINDS)})


@bp.route('/api/dental-vision/visits', methods=['POST'])
@require_auth
def api_add_visit():
    try:
        return jsonify({'success': True, 'visit': add_visit(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/dental-vision/visits/<vid>', methods=['DELETE'])
@require_auth
def api_delete_visit(vid):
    delete_visit(vid)
    return jsonify({'success': True})


@bp.route('/api/dental-vision/due')
@require_auth
def api_due():
    return jsonify({'due': get_due()})


@bp.route('/api/dental-vision/rx')
@require_auth
def api_rx():
    return jsonify({'prescriptions': list_rx(), 'kinds': list(RX_KINDS)})


@bp.route('/api/dental-vision/rx', methods=['POST'])
@require_auth
def api_add_rx():
    try:
        return jsonify({'success': True, 'prescription': add_rx(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/dental-vision/rx/<rid>', methods=['DELETE'])
@require_auth
def api_delete_rx(rid):
    delete_rx(rid)
    return jsonify({'success': True})
