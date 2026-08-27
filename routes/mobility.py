"""
routes/mobility.py — falls, hearing, and rehab exercises.

Falls    GET    /api/falls                    — the list
         POST   /api/falls                    — record one
         PATCH  /api/falls/<fid>              — edit one
         DELETE /api/falls/<fid>              — to the trash
         GET    /api/falls/summary            — counts, by place and time
         GET    /api/falls/meta               — the place/time vocabularies

Hearing  GET    /api/hearing                  — tests, aids and notes
         POST   /api/hearing                  — add one
         PATCH  /api/hearing/<rid>            — edit one
         DELETE /api/hearing/<rid>            — to the trash
         GET    /api/hearing/overview         — last test, aids, what is due

Rehab    GET    /api/rehab                    — plans, each with its adherence
         POST   /api/rehab                    — add a plan
         PATCH  /api/rehab/<pid>              — edit a plan
         DELETE /api/rehab/<pid>              — to the trash
         POST   /api/rehab/<pid>/log          — record a session done
         GET    /api/rehab/<pid>/sessions     — sessions + pain numbers
         DELETE /api/rehab/session/<lid>      — remove a session

None of these is walled off from a caregiver acting on someone's behalf, and
that is deliberate: falls, hearing aids and physiotherapy are exactly the things
a caregiver is there to help with. The private-diary wall covers mood, journal
and cycle — subjects where being managed is the problem rather than the point.
"""
from flask import Blueprint, request, jsonify, g

from auth import require_auth

bp = Blueprint('mobility', __name__)


def _body():
    return request.json if isinstance(request.json, dict) else {}


# ── Falls ───────────────────────────────────────────────────────────────────

@bp.route('/api/falls')
@require_auth
def api_falls():
    from db.falls import list_falls
    return jsonify({'falls': list_falls(since=request.args.get('since'))})


@bp.route('/api/falls/meta')
@require_auth
def api_falls_meta():
    """The place and time vocabularies, so the UI and the API cannot drift into
    offering different options."""
    from db.falls import PLACES, TIMES
    return jsonify({
        'places': [{'key': k, 'label': l} for k, l in PLACES],
        'times': [{'key': k, 'label': l} for k, l in TIMES],
    })


@bp.route('/api/falls', methods=['POST'])
@require_auth
def api_add_fall():
    from db.falls import add_fall
    b = _body()
    return jsonify({'success': True, 'fall': add_fall(
        fell_on=b.get('fell_on'), time_of_day=b.get('time_of_day'),
        place=b.get('place'), what_happened=b.get('what_happened'),
        injured=b.get('injured'), injury=b.get('injury'),
        got_up_alone=b.get('got_up_alone'), saw_someone=b.get('saw_someone'),
        notes=b.get('notes'))})


@bp.route('/api/falls/<fid>', methods=['PATCH'])
@require_auth
def api_update_fall(fid):
    from db.falls import update_fall, get_fall
    if not get_fall(fid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'fall': update_fall(fid, **_body())})


@bp.route('/api/falls/<fid>', methods=['DELETE'])
@require_auth
def api_delete_fall(fid):
    from db.falls import delete_fall, get_fall
    if not get_fall(fid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': bool(delete_fall(fid))})


@bp.route('/api/falls/summary')
@require_auth
def api_falls_summary():
    from db.falls import summary
    try:
        days = int(request.args.get('days', 365))
    except (TypeError, ValueError):
        days = 365
    return jsonify(summary(max(1, min(3650, days))))


# ── Hearing ─────────────────────────────────────────────────────────────────

@bp.route('/api/hearing')
@require_auth
def api_hearing():
    from db.hearing import list_records, KINDS
    return jsonify({'records': list_records(request.args.get('kind')),
                    'kinds': [{'key': k, 'label': l} for k, l in KINDS]})


@bp.route('/api/hearing', methods=['POST'])
@require_auth
def api_add_hearing():
    from db.hearing import add_record
    b = _body()
    return jsonify({'success': True, 'record': add_record(
        kind=b.get('kind', 'test'), record_date=b.get('record_date'),
        **{k: b.get(k) for k in ('provider', 'left_ear', 'right_ear', 'finding',
                                 'device', 'battery', 'serviced_on',
                                 'next_check', 'notes')})})


@bp.route('/api/hearing/<rid>', methods=['PATCH'])
@require_auth
def api_update_hearing(rid):
    from db.hearing import update_record, get_record
    if not get_record(rid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'record': update_record(rid, **_body())})


@bp.route('/api/hearing/<rid>', methods=['DELETE'])
@require_auth
def api_delete_hearing(rid):
    from db.hearing import delete_record, get_record
    if not get_record(rid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': bool(delete_record(rid))})


@bp.route('/api/hearing/overview')
@require_auth
def api_hearing_overview():
    from db.hearing import overview
    return jsonify(overview())


# ── Rehab ───────────────────────────────────────────────────────────────────

@bp.route('/api/rehab')
@require_auth
def api_rehab():
    """Plans with their adherence attached, because a plan without it is just a
    title and the number is the reason anyone opens this page."""
    from db.rehab import list_plans, adherence
    plans = list_plans()
    for p in plans:
        p['adherence'] = adherence(p['id'])
    return jsonify({'plans': plans})


@bp.route('/api/rehab', methods=['POST'])
@require_auth
def api_add_rehab_plan():
    from db.rehab import add_plan
    b = _body()
    try:
        plan = add_plan(
            name=b.get('name'), reason=b.get('reason'),
            prescribed_by=b.get('prescribed_by'),
            times_per_day=b.get('times_per_day', 1),
            started_on=b.get('started_on'), until_date=b.get('until_date'),
            instructions=b.get('instructions'))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    return jsonify({'success': True, 'plan': plan})


@bp.route('/api/rehab/<pid>', methods=['PATCH'])
@require_auth
def api_update_rehab_plan(pid):
    from db.rehab import update_plan, get_plan
    if not get_plan(pid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'plan': update_plan(pid, **_body())})


@bp.route('/api/rehab/<pid>', methods=['DELETE'])
@require_auth
def api_delete_rehab_plan(pid):
    from db.rehab import delete_plan, get_plan
    if not get_plan(pid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': bool(delete_plan(pid))})


@bp.route('/api/rehab/<pid>/log', methods=['POST'])
@require_auth
def api_log_rehab_session(pid):
    from db.rehab import log_session, adherence
    b = _body()
    try:
        session = log_session(pid, date_key=b.get('date_key'),
                              pain_after=b.get('pain_after'),
                              notes=b.get('notes'))
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    return jsonify({'success': True, 'session': session,
                    'adherence': adherence(pid)})


@bp.route('/api/rehab/<pid>/sessions')
@require_auth
def api_rehab_sessions(pid):
    from db.rehab import list_sessions, pain_trail, get_plan, adherence
    if not get_plan(pid):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'sessions': list_sessions(pid), 'pain': pain_trail(pid),
                    'adherence': adherence(pid)})


@bp.route('/api/rehab/session/<lid>', methods=['DELETE'])
@require_auth
def api_delete_rehab_session(lid):
    from db.core import execute
    from db.rehab import delete_session
    row = execute("SELECT id FROM rehab_logs WHERE id=? AND user_id=?",
                  (lid, g.user_id), fetchone=True)
    if not row:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': bool(delete_session(lid))})
