"""routes/health_id.py — the printable health ID card (read-only composer).

GET /api/health-id  — identity + emergency info + live active medicines.

Not in the acting-as private list: a caregiver managing a member SHOULD be able
to pull up that member's ID card in an emergency. Scoped by current_user_id, so
acting-as returns the managed member's card, not the caregiver's.
"""
from flask import Blueprint, jsonify
from auth import require_auth
from db.health_id import get_health_id

bp = Blueprint('health_id', __name__)


@bp.route('/api/health-id')
@require_auth
def api_health_id():
    return jsonify(get_health_id())
