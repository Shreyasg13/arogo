"""routes/health_id.py — the printable health ID card (read-only composer).

GET /api/health-id  — identity + emergency info + live active medicines.

Not in the acting-as private list: a caregiver managing a member SHOULD be able
to pull up that member's ID card in an emergency. Scoped by current_user_id, so
acting-as returns the managed member's card, not the caregiver's.
"""
from flask import Blueprint, jsonify
from auth import require_auth
from db.health_id import get_health_id
from db.health_binder import get_health_binder
from db.health import build_emergency_qr

bp = Blueprint('health_id', __name__)


@bp.route('/api/health-id')
@require_auth
def api_health_id():
    return jsonify(get_health_id())


@bp.route('/api/health-binder')
@require_auth
def api_health_binder():
    """The always-current, printable full health summary (N2). Read-only;
    composed entirely from the user's own records."""
    return jsonify(get_health_binder())


@bp.route('/api/health-id/qr')
@require_auth
def api_health_id_qr():
    """Self-contained SVG QR of the emergency summary for the ID card.
    `available:false` when segno isn't installed or there's nothing to encode."""
    return jsonify(build_emergency_qr())
