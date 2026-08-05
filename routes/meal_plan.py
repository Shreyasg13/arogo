"""routes/meal_plan.py — meal planner + grocery list.

GET    /api/meal-plan[?start=&days=7]   — the plan grid
POST   /api/meal-plan                   — {date, meal_type, item, quantity, unit}
DELETE /api/meal-plan/<id>
GET    /api/meal-plan/grocery[?start=&days=7]  — aggregated shopping list
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.meal_plan import add_planned, delete_planned, get_plan, get_grocery

bp = Blueprint('meal_plan', __name__)


@bp.route('/api/meal-plan')
@require_auth
def api_plan():
    return jsonify(get_plan(request.args.get('start'), request.args.get('days', 7)))


@bp.route('/api/meal-plan', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'item': add_planned(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/meal-plan/<pid>', methods=['DELETE'])
@require_auth
def api_delete(pid):
    delete_planned(pid)
    return jsonify({'success': True})


@bp.route('/api/meal-plan/grocery')
@require_auth
def api_grocery():
    return jsonify(get_grocery(request.args.get('start'), request.args.get('days', 7)))
