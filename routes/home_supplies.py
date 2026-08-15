"""routes/home_supplies.py — M2 home medical-supplies inventory.

First-aid kit + OTC basics with quantity, optional expiry, and an optional
restock threshold. All @require_auth and user-scoped; factual inventory only.

GET    /api/supplies[?category=first_aid|otc|device|other]
POST   /api/supplies                — {name, category, quantity, unit, expiry_date, low_at, notes}
PATCH  /api/supplies/<sid>          — {quantity, low_at, expiry_date, notes}
DELETE /api/supplies/<sid>
GET    /api/supplies/alerts         — expired / expiring / low-stock
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.home_supplies import (add_supply, update_supply, list_supplies, delete_supply,
                              get_alerts, CATEGORIES)

bp = Blueprint('home_supplies', __name__)


@bp.route('/api/supplies')
@require_auth
def api_list():
    return jsonify({'supplies': list_supplies(request.args.get('category')),
                    'categories': list(CATEGORIES)})


@bp.route('/api/supplies', methods=['POST'])
@require_auth
def api_add():
    try:
        return jsonify({'success': True, 'supply': add_supply(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/supplies/<sid>', methods=['PATCH'])
@require_auth
def api_update(sid):
    try:
        s = update_supply(sid, request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not s:
        return jsonify({'success': False, 'error': 'Item not found'}), 404
    return jsonify({'success': True, 'supply': s})


@bp.route('/api/supplies/<sid>', methods=['DELETE'])
@require_auth
def api_delete(sid):
    delete_supply(sid)
    return jsonify({'success': True})


@bp.route('/api/supplies/alerts')
@require_auth
def api_alerts():
    return jsonify(get_alerts())
