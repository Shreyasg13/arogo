"""
routes/security.py — two-factor sign-in, backups, and medicine reconciliation.

2FA         GET  /api/2fa                     — is it on, recovery codes left
            POST /api/2fa/setup               — start; returns secret + otpauth URI
            POST /api/2fa/confirm             — prove a code works; returns recovery codes ONCE
            POST /api/2fa/disable             — off (password required)
Backups     GET  /api/backups                 — status of the newest, verified now
            POST /api/backups/run             — take one on demand
Changes     GET  /api/medicines/changes       — what changed between two dates

The 2FA endpoints sit behind the acting-as wall: a caregiver managing someone's
health data has no business touching how they sign in.
"""
from flask import Blueprint, request, jsonify, g

from auth import require_auth

bp = Blueprint('security', __name__)


# ── Two-factor ──────────────────────────────────────────────────────────────

@bp.route('/api/2fa')
@require_auth
def api_2fa_status():
    from db.totp import is_enabled, recovery_codes_left
    return jsonify({'enabled': is_enabled(g.user_id),
                    'recovery_codes_left': recovery_codes_left(g.user_id)})


@bp.route('/api/2fa/setup', methods=['POST'])
@require_auth
def api_2fa_setup():
    """Start enrolment. Nothing is enforced yet — the secret exists but sign-in
    is untouched until a code proves the authenticator actually works."""
    from db.core import execute
    from db.totp import begin_enrolment, is_enabled
    if is_enabled(g.user_id):
        return jsonify({'success': False,
                        'error': 'Two-factor sign-in is already on.'}), 400
    row = execute('SELECT email FROM users WHERE id=?', (g.user_id,), fetchone=True)
    return jsonify({'success': True,
                    **begin_enrolment(g.user_id, (row or {}).get('email', 'account'))})


@bp.route('/api/2fa/confirm', methods=['POST'])
@require_auth
def api_2fa_confirm():
    """Switch it on, and hand back the recovery codes exactly once.

    Nothing keeps a readable copy after this response, so the UI must make the
    user acknowledge them before moving on — losing a phone is a foreseeable
    event, not an edge case.
    """
    from db.totp import confirm_enrolment
    res = confirm_enrolment(g.user_id, (request.json or {}).get('code'))
    if not res.get('ok'):
        return jsonify({'success': False, 'error': res.get('error')}), 400
    from db.account_activity import log_event
    log_event('two_factor_enabled')
    return jsonify({'success': True, 'recovery_codes': res['recovery_codes']})


@bp.route('/api/2fa/disable', methods=['POST'])
@require_auth
def api_2fa_disable():
    """Turning off a security control requires the password.

    Otherwise a borrowed unlocked phone is enough to strip the second factor,
    which would make the feature decorative.
    """
    from db.core import execute
    from auth import check_password
    from db.totp import disable, is_enabled
    if not is_enabled(g.user_id):
        return jsonify({'success': True})
    row = execute('SELECT password_hash FROM users WHERE id=?', (g.user_id,),
                  fetchone=True)
    if not row or not check_password((request.json or {}).get('password') or '',
                                     row['password_hash']):
        return jsonify({'success': False, 'error': 'That password is not right.'}), 401
    disable(g.user_id)
    from db.account_activity import log_event
    log_event('two_factor_disabled')
    return jsonify({'success': True})


# ── Backups ─────────────────────────────────────────────────────────────────

@bp.route('/api/backups')
@require_auth
def api_backups():
    """Status of the newest backup, verified on every call rather than trusted.
    The only thing worse than no backup is one everybody believes in."""
    from db.backups import status
    return jsonify(status())


@bp.route('/api/backups/run', methods=['POST'])
@require_auth
def api_backup_run():
    from db.backups import run_backup
    res = run_backup()
    return (jsonify(res), 200) if res.get('ok') else (jsonify(res), 500)


# ── What changed ────────────────────────────────────────────────────────────

@bp.route('/api/medicines/changes')
@require_auth
def api_medicine_changes():
    """Medicine changes in a window — by default, since the last appointment,
    which is the question actually being asked."""
    from db.reconciliation import changes_between, since_last_appointment
    since = request.args.get('since')
    until = request.args.get('until')
    if since or until:
        return jsonify(changes_between(since, until))
    return jsonify(since_last_appointment())
