"""routes/upcoming.py — forward-looking family health calendar.

GET /api/upcoming[?days=60] — merged upcoming appointments, lab rechecks,
prescription renewals, vaccines due, and future-dated dependent records.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from db.upcoming import get_upcoming

bp = Blueprint('upcoming', __name__)


@bp.route('/api/upcoming')
@require_auth
def api_upcoming():
    try:
        days = int(request.args.get('days', 60))
    except (TypeError, ValueError):
        days = 60
    return jsonify(get_upcoming(days))
