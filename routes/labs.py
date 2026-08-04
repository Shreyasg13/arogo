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
from db.immunizations import log_dose, delete_dose, get_record, get_catalog as vaccine_catalog_grouped
from db.timeline import get_timeline

bp = Blueprint('labs', __name__)


@bp.route('/api/timeline')
@require_auth
def api_timeline():
    raw = request.args.get('types', '').strip()
    types = [t for t in raw.split(',') if t] or None
    return jsonify(get_timeline(types=types))


@bp.route('/api/immunizations')
@require_auth
def api_immunizations():
    return jsonify(get_record())


@bp.route('/api/immunizations', methods=['POST'])
@require_auth
def api_immunizations_add():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'dose': log_dose(
            d.get('vaccine_key', ''), d.get('date_given', ''),
            d.get('dose_label', ''), d.get('notes', ''))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/immunizations/<vid>', methods=['DELETE'])
@require_auth
def api_immunizations_delete(vid):
    delete_dose(vid)
    return jsonify({'success': True})


@bp.route('/api/immunizations/catalog')
@require_auth
def api_immunizations_catalog():
    return jsonify(vaccine_catalog_grouped())


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
