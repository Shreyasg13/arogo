"""
routes/auth.py — Authentication endpoints

POST /auth/register   — create account
POST /auth/login      — log in, set session cookie
POST /auth/logout     — clear session cookie
GET  /auth/me         — return current user info
GET  /auth/verify/<token> — verify email address
"""

import re
from flask import Blueprint, request, jsonify, make_response, g

from auth import (
    hash_password, check_password, validate_password_strength,
    set_auth_cookie, clear_auth_cookie,
    make_verify_token, read_verify_token,
    make_reset_token, read_reset_token,
    bump_token_version,
    rate_limit_auth, require_auth,
)
from db.core import execute, new_id, now_iso
import mailer

bp = Blueprint('auth', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Top-level domains RFC 2606 and RFC 6761 set aside so they can never be
# registered as real ones. Every test and fixture in this repository uses them,
# which makes them a reliable marker for "this is scaffolding".
_RESERVED_TLDS = ('.test', '.example', '.invalid', '.localhost')


def _reserved_test_domain(email: str):
    """A refusal message when scaffolding is being written to the real database.

    A one-off script written to check a change end-to-end imported the app,
    registered e2e-…@x.test and wrote fixture rows into the live database.
    Nothing stopped it, and nothing would have said so afterwards either.

    These TLDs cannot exist on the internet, so refusing them costs no real
    person an account. It only applies to the live database: the test suite
    runs in memory and benchmarks point at their own file, and both must keep
    working — a guard that blocks the tests would simply be turned off.
    """
    from db.core import IS_LIVE_DB
    if not IS_LIVE_DB:
        return None
    domain = email.rsplit('@', 1)[-1]
    if domain.endswith(_RESERVED_TLDS):
        return ('That address uses a reserved test domain, so this looks like '
                'test data being written to the real database. Point '
                'MEDEASY_DB at another file first.')
    return None


# ── Register ───────────────────────────────────────────────────────────────────

@bp.route('/auth/register', methods=['POST'])
@rate_limit_auth
def register():
    d     = request.json or {}
    email = (d.get('email') or '').strip().lower()
    name  = (d.get('name')  or '').strip()[:80]
    pw    = d.get('password') or ''

    # Validate
    if not email or not EMAIL_RE.match(email):
        return jsonify({'error': 'Valid email address required'}), 400
    reserved = _reserved_test_domain(email)
    if reserved:
        return jsonify({'error': reserved}), 400
    name = name or email.split('@')[0]   # default to email prefix if blank
    pw_err = validate_password_strength(pw)
    if pw_err:
        return jsonify({'error': pw_err}), 400

    # Check duplicate
    existing = execute('SELECT id FROM users WHERE email = ?', (email,), fetchone=True)
    if existing:
        return jsonify({'error': 'An account with this email already exists'}), 409

    # Create user
    uid          = new_id()
    pw_hash      = hash_password(pw)
    verify_token = make_verify_token(uid)

    execute(
        '''INSERT INTO users (id, email, name, password_hash, verified, verify_token, created_at)
           VALUES (?, ?, ?, ?, 0, ?, ?)''',
        (uid, email, name, pw_hash, verify_token, now_iso()),
        commit=True,
    )

    # Create blank user_profile row for this user (onboarding will fill it)
    from db.core import new_id as nid
    execute(
        '''INSERT INTO user_profile
           (id, name, weight_kg, height_cm, age, gender,
            activity_level, goal, updated_at, user_id)
           VALUES (?, '', NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)''',
        (nid(), now_iso(), uid),
        commit=True,
    )

    # Send verification email (logged to stderr when SMTP isn't configured)
    mailer.send_verification_email(email, verify_token)

    resp = make_response(jsonify({
        'success': True,
        'user': {'id': uid, 'email': email, 'name': name, 'verified': False},
        'message': 'Account created. Check your email to verify.',
    }), 201)
    set_auth_cookie(resp, uid, new_session=True)
    return resp


# ── Login ──────────────────────────────────────────────────────────────────────

@bp.route('/auth/login', methods=['POST'])
@rate_limit_auth
def login():
    d     = request.json or {}
    email = (d.get('email') or '').strip().lower()
    pw    = d.get('password') or ''

    if not email or not pw:
        return jsonify({'error': 'Email and password required'}), 400

    row = execute('SELECT * FROM users WHERE email = ?', (email,), fetchone=True)

    # Constant-time rejection — don't reveal whether email exists
    dummy_hash = 'a' * 65 + ':' + 'b' * 64
    stored     = row['password_hash'] if row else dummy_hash
    valid      = check_password(pw, stored)

    if not row or not valid:
        return jsonify({'error': 'Incorrect email or password'}), 401

    # Second factor, when it is switched on AND confirmed. An unconfirmed
    # enrolment never gates a sign-in — a half-finished setup must not lock
    # someone out of their own medicines.
    from db.totp import is_enabled
    if is_enabled(row['id']):
        from auth import make_totp_challenge, TOTP_CHALLENGE_MAX_AGE
        # No cookie is set here. The challenge is signed with its own salt, so
        # it cannot be presented as a session.
        return jsonify({
            'success': False,
            'needs_2fa': True,
            'challenge': make_totp_challenge(row['id']),
            'expires_in': TOTP_CHALLENGE_MAX_AGE,
        }), 200

    # Update last_login
    execute('UPDATE users SET last_login = ? WHERE id = ?',
            (now_iso(), row['id']), commit=True)

    resp = make_response(jsonify({
        'success': True,
        'user': {
            'id':       row['id'],
            'email':    row['email'],
            'name':     row['name'],
            'verified': bool(row['verified']),
        },
    }))
    set_auth_cookie(resp, row['id'], new_session=True)
    return resp


@bp.route('/auth/login/2fa', methods=['POST'])
@rate_limit_auth
def login_2fa():
    """Finish a sign-in that stopped at the second factor.

    Rate-limited like every other auth route: a six-digit code is guessable in
    a million tries, and the limiter is what makes that irrelevant.
    """
    from auth import read_totp_challenge
    from db.totp import verify
    d = request.json or {}
    uid = read_totp_challenge(d.get('challenge') or '')
    if not uid:
        return jsonify({'error': 'That sign-in attempt expired. Start again.'}), 401
    if not verify(uid, d.get('code') or ''):
        return jsonify({'error': 'That code did not match.'}), 401

    row = execute('SELECT * FROM users WHERE id = ?', (uid,), fetchone=True)
    if not row:
        return jsonify({'error': 'Incorrect email or password'}), 401
    execute('UPDATE users SET last_login = ? WHERE id = ?', (now_iso(), uid), commit=True)
    resp = make_response(jsonify({
        'success': True,
        'user': {'id': row['id'], 'email': row['email'], 'name': row['name'],
                 'verified': bool(row['verified'])},
    }))
    set_auth_cookie(resp, row['id'], new_session=True)
    return resp


# ── Token issue (mobile / API clients) ─────────────────────────────────────────

@bp.route('/auth/token', methods=['POST'])
@rate_limit_auth
def issue_token():
    """Same credential check as login, but returns the token in the body
    for clients that can't use cookies (native apps, scripts).
    Send it back as `Authorization: Bearer <token>`. Tokens expire after
    7 days and die immediately on password change/reset."""
    from auth import make_token, TOKEN_MAX_AGE
    d     = request.json or {}
    email = (d.get('email') or '').strip().lower()
    pw    = d.get('password') or ''
    if not email or not pw:
        return jsonify({'error': 'Email and password required'}), 400

    row = execute('SELECT * FROM users WHERE email = ?', (email,), fetchone=True)
    dummy_hash = 'a' * 65 + ':' + 'b' * 64
    valid = check_password(pw, row['password_hash'] if row else dummy_hash)
    if not row or not valid:
        return jsonify({'error': 'Incorrect email or password'}), 401

    execute('UPDATE users SET last_login = ? WHERE id = ?',
            (now_iso(), row['id']), commit=True)
    return jsonify({
        'success': True,
        'token': make_token(row['id']),
        'token_type': 'Bearer',
        'expires_in': TOKEN_MAX_AGE,
        'user': {'id': row['id'], 'email': row['email'], 'name': row['name'],
                 'verified': bool(row['verified'])},
    })


# ── Logout ─────────────────────────────────────────────────────────────────────

@bp.route('/auth/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'success': True}))
    clear_auth_cookie(resp)
    return resp


# ── Me ─────────────────────────────────────────────────────────────────────────

@bp.route('/auth/me')
@require_auth
def me():
    row = execute('SELECT id, email, name, verified, created_at, last_login FROM users WHERE id = ?',
                  (g.user_id,), fetchone=True)
    if not row:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'id':         row['id'],
        'email':      row['email'],
        'name':       row['name'],
        'verified':   bool(row['verified']),
        'created_at': row['created_at'],
        'last_login': row['last_login'],
    })


# ── Email verification ─────────────────────────────────────────────────────────

@bp.route('/auth/verify/<token>')
def verify_email(token):
    """Opened from the email link in a browser — redirect into the SPA,
    which shows a toast based on ?verified=1/0."""
    from flask import redirect
    uid = read_verify_token(token)
    row = execute('SELECT id, verified FROM users WHERE id = ?', (uid,), fetchone=True) if uid else None
    if not row:
        return redirect('/?verified=0')
    if not row['verified']:
        execute('UPDATE users SET verified = 1, verify_token = NULL WHERE id = ?',
                (uid,), commit=True)
    return redirect('/?verified=1')


@bp.route('/auth/resend-verification', methods=['POST'])
@require_auth
@rate_limit_auth
def resend_verification():
    row = execute('SELECT email, verified FROM users WHERE id = ?', (g.user_id,), fetchone=True)
    if not row:
        return jsonify({'error': 'User not found'}), 404
    if row['verified']:
        return jsonify({'success': True, 'message': 'Your email is already verified'})
    from db import get_user_language
    mailer.send_verification_email(row['email'], make_verify_token(g.user_id),
                                   lang=get_user_language(g.user_id))
    return jsonify({'success': True, 'message': f"Verification email sent to {row['email']}"})


# ── Password reset ─────────────────────────────────────────────────────────────

@bp.route('/auth/forgot-password', methods=['POST'])
@rate_limit_auth
def forgot_password():
    d     = request.json or {}
    email = (d.get('email') or '').strip().lower()
    if not email or not EMAIL_RE.match(email):
        return jsonify({'error': 'Valid email address required'}), 400

    # Always report success — never reveal whether the email is registered
    row = execute('SELECT id FROM users WHERE email = ?', (email,), fetchone=True)
    if row:
        from db import get_user_language
        mailer.send_password_reset_email(email, make_reset_token(row['id']),
                                         lang=get_user_language(row['id']))

    return jsonify({'success': True,
                    'message': 'If that email is registered, a reset link is on its way.'})


@bp.route('/auth/reset-password', methods=['POST'])
@rate_limit_auth
def reset_password():
    d      = request.json or {}
    token  = d.get('token') or ''
    new_pw = d.get('password') or ''

    uid = read_reset_token(token)
    if not uid:
        return jsonify({'error': 'Invalid or expired reset link. Request a new one.'}), 400

    pw_err = validate_password_strength(new_pw)
    if pw_err:
        return jsonify({'error': pw_err}), 400

    row = execute('SELECT id FROM users WHERE id = ?', (uid,), fetchone=True)
    if not row:
        return jsonify({'error': 'User not found'}), 404

    execute('UPDATE users SET password_hash = ? WHERE id = ?',
            (hash_password(new_pw), uid), commit=True)
    bump_token_version(uid)   # log out every existing session
    return jsonify({'success': True, 'message': 'Password updated. You can log in now.'})


# ── Change password ────────────────────────────────────────────────────────────

@bp.route('/auth/change-password', methods=['POST'])
@require_auth
@rate_limit_auth
def change_password():
    d       = request.json or {}
    current = d.get('current_password') or ''
    new_pw  = d.get('new_password') or ''

    row = execute('SELECT password_hash FROM users WHERE id = ?',
                  (g.user_id,), fetchone=True)
    if not row:
        return jsonify({'error': 'User not found'}), 404
    if not check_password(current, row['password_hash']):
        return jsonify({'error': 'Current password is incorrect'}), 401

    pw_err = validate_password_strength(new_pw)
    if pw_err:
        return jsonify({'error': pw_err}), 400

    execute('UPDATE users SET password_hash = ? WHERE id = ?',
            (hash_password(new_pw), g.user_id), commit=True)
    # Revoke all sessions (including this one), then keep the current
    # browser signed in with a freshly-minted cookie
    bump_token_version(g.user_id)
    # Every other device is now signed out; record both facts, and give this
    # browser a fresh session so it can still be listed and revoked later.
    from db.account_activity import revoke_all_sessions, log_event
    revoke_all_sessions(g.user_id)
    log_event('password_changed', uid=g.user_id)
    resp = make_response(jsonify({'success': True, 'message': 'Password updated'}))
    set_auth_cookie(resp, g.user_id, new_session=True)
    return resp


@bp.route('/api/account/export', methods=['GET'])
@require_auth
def account_export():
    """Download everything we hold about this user (GDPR/DPDP data access)."""
    import json as _json
    from db.account import export_all_data
    data = export_all_data(g.user_id)
    payload = _json.dumps(data, indent=2, ensure_ascii=False, default=str)
    resp = make_response(payload)
    resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="arogo-my-data.json"'
    return resp


@bp.route('/api/export/categories')
@require_auth
def export_categories():
    """The pickable categories for a scoped export (Category 2 — data control)."""
    from db.account import EXPORT_CATEGORIES
    return jsonify({'categories': [{'key': k, 'label': lbl} for k, lbl, _t in EXPORT_CATEGORIES]})


@bp.route('/api/export/scoped', methods=['POST'])
@require_auth
def account_export_scoped():
    """Download ONLY the chosen categories — hand a doctor just labs, or share
    everything-but-diary. Health data only; never account/secret meta."""
    import json as _json
    from db.account import export_selected_data
    cats = (request.get_json(silent=True) or {}).get('categories')
    data = export_selected_data(g.user_id, cats if isinstance(cats, list) else [])
    payload = _json.dumps(data, indent=2, ensure_ascii=False, default=str)
    resp = make_response(payload)
    resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="arogo-selected-data.json"'
    return resp


@bp.route('/api/account', methods=['DELETE'])
@require_auth
@rate_limit_auth
def account_delete():
    """Hard-delete the account and all associated data. Requires the password."""
    d = request.json or {}
    row = execute('SELECT password_hash FROM users WHERE id = ?', (g.user_id,), fetchone=True)
    if not row:
        return jsonify({'error': 'User not found'}), 404
    if not check_password(d.get('password') or '', row['password_hash']):
        return jsonify({'error': 'Password is incorrect'}), 401
    from db.account import delete_account
    delete_account(g.user_id)
    resp = make_response(jsonify({'success': True}))
    clear_auth_cookie(resp)
    return resp