"""routes/workouts.py — structured strength-training log.

GET    /api/workouts                 — recent sessions (grouped sets)
POST   /api/workouts                 — log a set {exercise, reps, weight, unit, date_key}
DELETE /api/workouts/<id>            — delete a set
GET    /api/workouts/exercises       — distinct exercise names (for quick-pick)
GET    /api/workouts/progression?exercise=Bench Press
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.workouts import (log_set, delete_set, list_exercises,
                         get_workout_log, get_progression)

bp = Blueprint('workouts', __name__)


@bp.route('/api/workouts')
@require_auth
def api_log():
    from db.core import to_int
    days = to_int(request.args.get('days', 30), 30, lo=1, hi=3650)
    return jsonify(get_workout_log(days))


@bp.route('/api/workouts', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'set': log_set(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/workouts/<sid>', methods=['DELETE'])
@require_auth
def api_delete(sid):
    delete_set(sid)
    return jsonify({'success': True})


@bp.route('/api/workouts/exercises')
@require_auth
def api_exercises():
    return jsonify({'exercises': list_exercises()})


@bp.route('/api/workouts/progression')
@require_auth
def api_progression():
    exercise = request.args.get('exercise', '')
    if not exercise.strip():
        return jsonify({'success': False, 'error': 'exercise required'}), 400
    return jsonify(get_progression(exercise))
