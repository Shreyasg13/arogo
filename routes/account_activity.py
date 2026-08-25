"""
routes/account_activity.py — where you're signed in, and what changed.

GET    /api/account/sessions           — devices currently signed in
DELETE /api/account/sessions/<id>      — sign out one device
POST   /api/account/sessions/revoke-all— sign out everywhere else
GET    /api/account/activity           — the security log
GET    /api/account/shares             — share links and whether they were opened

Walled from acting-as: a caregiver managing someone's health data has no
business seeing their devices, or signing them out.
"""
from flask import Blueprint, jsonify, g

from auth import require_auth

bp = Blueprint('account_activity', __name__)


@bp.route('/api/account/sessions')
@require_auth
def api_sessions():
    from db.account_activity import list_sessions
    return jsonify({'sessions': list_sessions(getattr(g, 'session_id', None))})


@bp.route('/api/account/sessions/<sid>', methods=['DELETE'])
@require_auth
def api_revoke_session(sid):
    from db.account_activity import revoke_session
    return jsonify({'success': revoke_session(sid)})


@bp.route('/api/account/sessions/revoke-all', methods=['POST'])
@require_auth
def api_revoke_all():
    """Sign out every other device, keeping this one.

    token_version is deliberately NOT bumped: that would also sign out THIS
    browser and every pre-session token at once, which is the blunt instrument
    this feature exists to replace. Anyone who wants that has "change password",
    which still does it.
    """
    from db.account_activity import revoke_all_sessions
    n = revoke_all_sessions(g.user_id, keep_sid=getattr(g, 'session_id', None))
    return jsonify({'success': True, 'signed_out': n})


@bp.route('/api/account/activity')
@require_auth
def api_activity():
    from db.account_activity import list_events
    return jsonify({'events': list_events()})


@bp.route('/api/account/shares')
@require_auth
def api_shares():
    from db.account_activity import share_receipts
    return jsonify({'shares': share_receipts()})
