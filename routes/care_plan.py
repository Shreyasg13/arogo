"""routes/care_plan.py — shared care plan.

GET    /api/care-plan            — all items + summary + category/owner vocab
POST   /api/care-plan            — {title, detail, category, owner, review_date}
PATCH  /api/care-plan/<id>       — any of the above + {status: active|done}
DELETE /api/care-plan/<id>

Shared via the caregiver acting-as model (scoped by current_user_id); not in the
acting-as private list, so a caregiver managing a member sees that member's plan.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.care_plan import create_item, update_item, delete_item, list_plan

bp = Blueprint('care_plan', __name__)


@bp.route('/api/care-plan')
@require_auth
def api_list():
    return jsonify(list_plan())


@bp.route('/api/care-plan', methods=['POST'])
@require_auth
def api_create():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'item': create_item(
            d.get('title', ''), d.get('detail', ''), d.get('category', 'other'),
            d.get('owner', 'me'), d.get('review_date'))})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/care-plan/<iid>', methods=['PATCH'])
@require_auth
def api_update(iid):
    try:
        return jsonify({'success': True, 'item': update_item(iid, request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/care-plan/<iid>', methods=['DELETE'])
@require_auth
def api_delete(iid):
    delete_item(iid)
    return jsonify({'success': True})
