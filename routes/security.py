"""
routes/security.py — two-factor sign-in, backups, and medicine reconciliation.

2FA         GET  /api/2fa                     — is it on, recovery codes left
            POST /api/2fa/setup               — start; returns secret + otpauth URI
            POST /api/2fa/confirm             — prove a code works; returns recovery codes ONCE
            POST /api/2fa/disable             — off (password required)
            POST /api/2fa/recovery-codes      — a fresh set (password required)
Backups     GET  /api/backups                 — status of the newest, verified now
            POST /api/backups/run             — take one on demand
Changes     GET  /api/medicines/changes       — what changed between two dates
Visit pack  GET  /api/visit-pack              — one appointment, everything to bring
            GET  /api/visit-pack/appointments — which appointments can have one

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
    out = begin_enrolment(g.user_id, (row or {}).get('email', 'account'))
    # A scannable QR when segno is installed, and the secret to type in by hand
    # when it isn't — the fallback is the whole reason `available` is reported
    # rather than the QR just being missing.
    from db.health import qr_svg
    out['qr'] = qr_svg(out['uri'], echo_text=False)
    return jsonify({'success': True, **out})


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


@bp.route('/api/2fa/recovery-codes', methods=['POST'])
@require_auth
def api_2fa_new_recovery_codes():
    """A fresh set of recovery codes, password required.

    Same reasoning as disabling: these codes bypass the second factor, so
    minting them is a security action, not a convenience one.
    """
    from db.core import execute
    from auth import check_password
    from db.totp import regenerate_recovery_codes, is_enabled
    if not is_enabled(g.user_id):
        return jsonify({'success': False,
                        'error': 'Two-factor sign-in is not on.'}), 400
    row = execute('SELECT password_hash FROM users WHERE id=?', (g.user_id,),
                  fetchone=True)
    if not row or not check_password((request.json or {}).get('password') or '',
                                     row['password_hash']):
        return jsonify({'success': False, 'error': 'That password is not right.'}), 401
    codes = regenerate_recovery_codes(g.user_id)
    from db.account_activity import log_event
    log_event('two_factor_recovery_codes_regenerated')
    return jsonify({'success': True, 'recovery_codes': codes})


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


# ── The appointment pack ────────────────────────────────────────────────────

@bp.route('/api/visit-pack')
@require_auth
def api_visit_pack():
    """One appointment's worth of everything, ready to print.

    With no `appointment` the soonest upcoming one is used; with `since`/`until`
    and no appointment it builds the same page for a plain date range, because
    not every visit is booked through Arogo.
    """
    from db.visit_pack import build_pack, next_appointment, pack_for_dates
    aid = request.args.get('appointment')
    if not aid and (request.args.get('since') or request.args.get('until')):
        return jsonify({'success': True,
                        'pack': pack_for_dates(request.args.get('since'),
                                               request.args.get('until'))})
    aid = aid or next_appointment()
    if not aid:
        # No appointments at all is a normal state, not an error — fall back to
        # the date-range pack rather than showing an empty screen.
        return jsonify({'success': True, 'pack': pack_for_dates(None, None),
                        'no_appointments': True})
    pack = build_pack(aid)
    if pack is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'pack': pack})


@bp.route('/api/visit-pack/appointments')
@require_auth
def api_visit_pack_appointments():
    """The appointments a pack can be built for — upcoming first, then recent
    past ones, since packs get printed after a visit too."""
    from db.core import execute, user_today
    today = user_today()
    rows = execute("""SELECT id, title, date, time, kind FROM appointments
                      WHERE user_id=? ORDER BY date DESC LIMIT 40""",
                   (g.user_id,), fetchall=True) or []
    items = [{'id': r['id'], 'title': r['title'], 'date': r['date'],
              'time': r['time'] or '', 'kind': r['kind'] or 'doctor',
              'upcoming': str(r['date']) >= today} for r in rows]
    items.sort(key=lambda a: (not a['upcoming'],
                              a['date'] if a['upcoming'] else ''))
    return jsonify({'appointments': items})
