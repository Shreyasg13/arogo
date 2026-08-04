"""routes/labs.py — lab-panel results + trends.

GET    /api/labs               — latest value per test (decorated with range/status)
POST   /api/labs               — log a value {lab_key, value, date_key, notes}
DELETE /api/labs/<lid>         — remove a value
GET    /api/labs/catalog       — the test catalog (grouped, sex-aware ranges)
GET    /api/labs/trend/<key>   — one test's history for a chart
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.labs import (log_lab_result, delete_lab_result, get_latest_by_test,
                     get_lab_trend, get_catalog)
from db.conditions import list_conditions, get_condition_dashboard

bp = Blueprint('labs', __name__)


@bp.route('/api/conditions')
@require_auth
def api_conditions_list():
    return jsonify({'conditions': list_conditions()})


@bp.route('/api/conditions/<key>')
@require_auth
def api_condition_dashboard(key):
    try:
        return jsonify(get_condition_dashboard(key))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@bp.route('/api/labs')
@require_auth
def api_labs_list():
    return jsonify({'results': get_latest_by_test()})


@bp.route('/api/labs', methods=['POST'])
@require_auth
def api_labs_add():
    d = request.json or {}
    try:
        r = log_lab_result(d.get('lab_key', ''), d.get('value'),
                           d.get('date_key', ''), d.get('notes', ''))
        return jsonify({'success': True, 'result': r})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/labs/<lid>', methods=['DELETE'])
@require_auth
def api_labs_delete(lid):
    delete_lab_result(lid)
    return jsonify({'success': True})


@bp.route('/api/labs/catalog')
@require_auth
def api_labs_catalog():
    return jsonify(get_catalog())


@bp.route('/api/labs/trend/<key>')
@require_auth
def api_labs_trend(key):
    return jsonify(get_lab_trend(key))
