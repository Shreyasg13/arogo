"""
routes/family.py — Family sharing endpoints (Phase 3).

GET    /api/family                       — my group (or null)
POST   /api/family                       — create group {name}
DELETE /api/family                       — delete group (owner, must be empty)
POST   /api/family/leave                 — leave group (members only)
DELETE /api/family/member/<uid>          — remove member (owner)
POST   /api/family/consent               — update my consent flags
POST   /api/family/invite                — send invite {email} (owner)
DELETE /api/family/invite/<invite_id>    — revoke pending invite (owner)
POST   /api/family/invite/accept         — accept invite {token} (logged-in invitee)
GET    /api/family/member/<uid>/summary  — consent-gated member summary
"""
import re
from flask import Blueprint, request, jsonify, g

from auth import require_auth, make_family_invite_token, read_family_invite_token
from db import family
from db.core import execute
import mailer

bp = Blueprint('family', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _err(e):
    return jsonify({'error': str(e)}), 400


@bp.route('/api/family')
@require_auth
def get_group():
    return jsonify({'group': family.get_my_group()})


@bp.route('/api/family', methods=['POST'])
@require_auth
def create_group():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'group': family.create_group((d.get('name') or '').strip()[:60])})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family', methods=['DELETE'])
@require_auth
def delete_group():
    try:
        family.delete_group()
        return jsonify({'success': True})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/leave', methods=['POST'])
@require_auth
def leave_group():
    try:
        family.leave_group()
        return jsonify({'success': True})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/member/<uid>', methods=['DELETE'])
@require_auth
def remove_member(uid):
    try:
        family.remove_member(uid)
        return jsonify({'success': True})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/consent', methods=['POST'])
@require_auth
def update_consent():
    d = request.json or {}
    try:
        return jsonify({'success': True, 'consent': family.update_consent(d)})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/invite', methods=['POST'])
@require_auth
def send_invite():
    d = request.json or {}
    email = (d.get('email') or '').strip().lower()
    if not email or not EMAIL_RE.match(email):
        return jsonify({'error': 'Valid email address required'}), 400
    try:
        inv = family.create_invite(email)
    except ValueError as e:
        return _err(e)

    me = execute("SELECT name, email FROM users WHERE id=?", (g.user_id,), fetchone=True)
    group = family.get_my_group()
    mailer.send_family_invite_email(
        email, make_family_invite_token(inv['id']),
        (me['name'] or me['email']) if me else 'Someone',
        group['name'] if group else 'My Family')
    return jsonify({'success': True, 'invite': inv})


@bp.route('/api/family/invite/<invite_id>', methods=['DELETE'])
@require_auth
def revoke_invite(invite_id):
    try:
        family.revoke_invite(invite_id)
        return jsonify({'success': True})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/invite/accept', methods=['POST'])
@require_auth
def accept_invite():
    d = request.json or {}
    invite_id = read_family_invite_token(d.get('token') or '')
    if not invite_id:
        return jsonify({'error': 'Invalid or expired invite link'}), 400
    try:
        return jsonify({'success': True, 'group': family.accept_invite(invite_id)})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/member/<uid>/summary')
@require_auth
def member_summary(uid):
    try:
        return jsonify(family.member_summary(uid))
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403


@bp.route('/api/family/care-status')
@require_auth
def care_status():
    """Today's dose status for family members who share their meds with me."""
    return jsonify(family.care_status())


@bp.route('/api/family/care-ack', methods=['POST'])
@require_auth
def care_ack():
    """Claim 'I'll check on this' for a family member so co-caregivers see it."""
    target = (request.json or {}).get('target_user_id')
    if not target:
        return jsonify({'error': 'target_user_id required'}), 400
    try:
        return jsonify(family.ack_care(target))
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
