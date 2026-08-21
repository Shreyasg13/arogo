"""routes/experiments.py — honest N-of-1 self-experiments (before/after)."""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.experiments import (metric_options, create_experiment, list_experiments,
                            end_experiment, delete_experiment)

bp = Blueprint('experiments', __name__)


@bp.route('/api/experiments')
@require_auth
def api_list():
    return jsonify({'experiments': list_experiments(), 'metrics': metric_options()})


@bp.route('/api/experiments', methods=['POST'])
@require_auth
def api_create():
    try:
        return jsonify({'success': True, 'experiment': create_experiment(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/experiments/<eid>/end', methods=['POST'])
@require_auth
def api_end(eid):
    return jsonify({'success': True, 'experiment': end_experiment(eid)})


@bp.route('/api/experiments/<eid>', methods=['DELETE'])
@require_auth
def api_delete(eid):
    delete_experiment(eid)
    return jsonify({'success': True})
