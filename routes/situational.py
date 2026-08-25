"""
routes/situational.py — the states a life actually goes through.

Trips        GET/POST /api/trips, DELETE /api/trips/<id>, GET /api/trips/clock
Episodes     GET/POST /api/episodes, PUT/DELETE /api/episodes/<id>,
             POST /api/episodes/<id>/end, GET /api/episodes/<id>/summary
Courses      GET /api/courses

None of these invent a schema; trips and episodes are two small tables, and
courses read dates already stored on a medicine.

Medicine expiry is NOT here: /api/medicines/expiring already existed and does
the same job. What was missing was what to DO about an expired box, which is
in db/courses.disposal_guidance().
"""
from flask import Blueprint, request, jsonify

from auth import require_auth

bp = Blueprint('situational', __name__)


# ── Trips ───────────────────────────────────────────────────────────────────

@bp.route('/api/trips')
@require_auth
def api_trips():
    from db.trips import list_trips, timezone_choices
    return jsonify({'trips': list_trips(), 'timezones': timezone_choices()})


@bp.route('/api/trips', methods=['POST'])
@require_auth
def api_create_trip():
    from db.trips import create_trip
    try:
        return jsonify({'success': True, 'trip': create_trip(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/trips/<tid>', methods=['DELETE'])
@require_auth
def api_delete_trip(tid):
    from db.trips import delete_trip
    return jsonify({'success': delete_trip(tid)})


@bp.route('/api/trips/<tid>/supply')
@require_auth
def api_trip_supply(tid):
    """What to pack for this trip, using the planner that already existed.

    A trip now feeds it directly instead of the user re-typing the dates into a
    separate screen — same arithmetic, one source for the dates."""
    from db.trips import get_trip
    from db.travel import plan_travel_supply
    trip = get_trip(tid)
    if not trip:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(plan_travel_supply(trip['start_date'], trip['end_date']))


@bp.route('/api/trips/clock')
@require_auth
def api_trip_clock():
    """Both clocks, side by side, with no recommendation.

    Whether to move an 8am tablet to 8am local, shift it gradually, or hold it
    twelve hours from the last one is a medical question — and a consequential
    one for insulin, anticoagulants or contraceptives. The app shows the shift
    and leaves the decision where it belongs.
    """
    from db.trips import dose_clock
    from db.food import get_home_timezone
    return jsonify(dose_clock(get_home_timezone()))


# ── Illness episodes ────────────────────────────────────────────────────────

@bp.route('/api/episodes')
@require_auth
def api_episodes():
    from db.episodes import list_episodes
    return jsonify({'episodes': list_episodes()})


@bp.route('/api/episodes', methods=['POST'])
@require_auth
def api_create_episode():
    from db.episodes import create_episode
    try:
        return jsonify({'success': True, 'episode': create_episode(request.json or {})})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@bp.route('/api/episodes/<eid>', methods=['PUT'])
@require_auth
def api_update_episode(eid):
    from db.episodes import update_episode
    try:
        ep = update_episode(eid, request.json or {})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    if not ep:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True, 'episode': ep})


@bp.route('/api/episodes/<eid>/end', methods=['POST'])
@require_auth
def api_end_episode(eid):
    from db.episodes import end_episode
    ep = end_episode(eid, (request.json or {}).get('ended_on'))
    if not ep:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True, 'episode': ep})


@bp.route('/api/episodes/<eid>', methods=['DELETE'])
@require_auth
def api_delete_episode(eid):
    """Removes the grouping only — every symptom and reading it covered stays."""
    from db.episodes import delete_episode
    return jsonify({'success': delete_episode(eid)})


@bp.route('/api/episodes/<eid>/summary')
@require_auth
def api_episode_summary(eid):
    from db.episodes import episode_summary
    s = episode_summary(eid)
    return (jsonify(s), 200) if s else (jsonify({'error': 'Not found'}), 404)


# ── Courses ─────────────────────────────────────────────────────────────────

@bp.route('/api/courses')
@require_auth
def api_courses():
    from db.courses import list_courses
    return jsonify({'courses': list_courses()})

@bp.route('/api/medicines/disposal')
@require_auth
def api_disposal():
    """What to do with an expired box.

    /api/medicines/expiring already says WHICH medicines are out of date. This
    is the part that was missing, and it is deliberately thin: disposal rules
    are local and legally specific, and the app knows a country only well enough
    to pick a currency symbol.
    """
    from db.courses import disposal_guidance
    from db.food import get_profile
    return jsonify(disposal_guidance((get_profile() or {}).get('country')))
