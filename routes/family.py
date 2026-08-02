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


@bp.route('/api/sos', methods=['POST'])
@require_auth
def sos():
    """Urgent 'I need help now' — the user taps this themselves (their explicit
    action) and it immediately alerts their caregivers: app-user family who
    receive care alerts (push + email) and zero-install contacts (SMS/WhatsApp),
    reusing the same delivery the missed-dose escalation uses. Honest about who
    was actually reached — an emergency button must never silently reach nobody.
    """
    import push, sms
    from db.core import current_user_id
    from db import add_notification
    uid = current_user_id()
    urow = execute("SELECT name, email FROM users WHERE id=?", (uid,), fetchone=True)
    name = (urow['name'] if urow else '') or (urow['email'] if urow else 'A family member')
    note = str((request.json or {}).get('note', '') or '').strip()[:200]

    title = f"🆘 {name} needs help"
    body = "They sent an urgent SOS from Arogo. Please check on them now."
    if note:
        body += f' Note: "{note}"'

    reached, who = 0, []

    me = execute("SELECT group_id FROM family_members WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    if me:
        others = execute("""
            SELECT u.id, u.email, u.name FROM family_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.group_id=? AND m.user_id<>? AND m.receive_care_alerts=1""",
            (me['group_id'], uid), fetchall=True) or []
        for o in others:
            pushed = bool(push.push_to_user(o['id'], title, body, '/'))
            # Same honesty rule as the escalation: a dev-mode email (printed, not
            # sent) doesn't count as reaching a human.
            sent = mailer.send_email(
                o['email'], title,
                f"Hi {o['name'] or 'there'},\n\n{body}\n\nOpen Arogo: {mailer.APP_BASE_URL}/\n")
            if pushed or (sent and mailer.is_configured()):
                reached += 1
                who.append(o['name'] or o['email'])

    contacts = execute("""SELECT id, name, phone, channel FROM caregiver_contacts
                          WHERE user_id=? AND alerts_enabled=1""", (uid,), fetchall=True) or []
    for c in contacts:
        msg = (f"Arogo SOS: {name} needs help now."
               + (f' Note: {note}' if note else '') + " Please check on them.")
        if sms.notify_contact(c, msg) and sms.is_configured(c.get('channel', 'sms')):
            reached += 1
            who.append(c['name'])

    # Transparency — the member's own feed records what happened.
    add_notification('care', 'SOS sent',
                     f"You sent an urgent alert to {reached} caregiver{'s' if reached != 1 else ''}."
                     if reached else
                     "You tapped SOS, but no caregiver could be reached — add one in Family.")

    return jsonify({'success': True, 'reached': reached, 'who': who})


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


@bp.route('/api/family/member/<uid>/display', methods=['POST'])
@require_auth
def set_member_display(uid):
    """Caregiver flips a consenting member's Simple View. Consent-gated in the
    data layer; only the ui_mode field is writable cross-user."""
    mode = (request.json or {}).get('ui_mode', 'simple')
    try:
        return jsonify({'success': True, 'result': family.set_member_ui_mode(uid, mode)})
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except ValueError as e:
        return _err(e)


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


@bp.route('/api/family/encourage', methods=['POST'])
@require_auth
def encourage():
    """Send a family member a bit of encouragement."""
    d = request.json or {}
    if not d.get('to_user_id'):
        return jsonify({'error': 'to_user_id required'}), 400
    try:
        return jsonify(family.send_encouragement(
            d['to_user_id'], d.get('emoji', '👏'), d.get('message', '')))
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/family/ping', methods=['POST'])
@require_auth
def ping():
    """Send a family member a 'thinking of you' ping (invites an I'm-okay reply)."""
    d = request.json or {}
    if not d.get('to_user_id'):
        return jsonify({'error': 'to_user_id required'}), 400
    try:
        return jsonify(family.send_encouragement(
            d['to_user_id'], '💛', 'Sending you a little care today.', kind='ping'))
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/family/encouragements')
@require_auth
def encouragements():
    """Unread encouragements addressed to me."""
    return jsonify(family.get_my_encouragements())


@bp.route('/api/family/encouragements/<eid>/ok', methods=['POST'])
@require_auth
def encouragement_reply_ok(eid):
    """Answer a 'thinking of you' ping with "I'm okay" (pings the sender back)."""
    try:
        return jsonify(family.reply_okay(eid))
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403


@bp.route('/api/family/encouragements/read', methods=['POST'])
@require_auth
def encouragements_read():
    family.mark_encouragements_read()
    return jsonify({'success': True})


# ── Zero-install caregiver alert contacts (SMS/WhatsApp, no account) ──────────

@bp.route('/api/family/alert-contacts', methods=['GET'])
@require_auth
def list_alert_contacts():
    import sms
    return jsonify({
        'contacts': family.list_caregiver_contacts(),
        # so the UI can be honest about whether messages will actually send
        'sms_live':      sms.is_configured('sms'),
        'whatsapp_live': sms.is_configured('whatsapp'),
    })


@bp.route('/api/family/alert-contacts', methods=['POST'])
@require_auth
def add_alert_contact():
    d = request.json or {}
    try:
        c = family.add_caregiver_contact(
            d.get('name', ''), d.get('phone', ''), d.get('channel', 'sms'))
        return jsonify({'success': True, 'contact': c})
    except ValueError as e:
        return _err(e)


@bp.route('/api/family/alert-contacts/<cid>', methods=['PATCH'])
@require_auth
def update_alert_contact(cid):
    d = request.json or {}
    ok = family.update_caregiver_contact(
        cid, alerts_enabled=d.get('alerts_enabled'), channel=d.get('channel'))
    if not ok:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True})


@bp.route('/api/family/alert-contacts/<cid>', methods=['DELETE'])
@require_auth
def delete_alert_contact(cid):
    if not family.delete_caregiver_contact(cid):
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'success': True})


@bp.route('/api/family/alert-contacts/<cid>/test', methods=['POST'])
@require_auth
def test_alert_contact(cid):
    """Send a one-off test so the member can confirm the number works."""
    import sms
    contact = next((c for c in family.list_caregiver_contacts() if c['id'] == cid), None)
    if not contact:
        return jsonify({'error': 'Not found'}), 404
    me = execute("SELECT name FROM users WHERE id=?", (g.user_id,), fetchone=True)
    who = (me['name'] if me and me['name'] else 'Someone') + " set up Arogo alerts"
    sent = sms.notify_contact(
        contact,
        f"{who} for you. If a dose is missed, you'll get a heads-up here. "
        f"This is just a test — nothing to do.")
    live = sms.is_configured(contact.get('channel', 'sms'))
    return jsonify({'success': True, 'delivered': bool(sent and live),
                    'dev_mode': not live})
