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
    rate_limit_auth, require_auth,
)
from db.core import execute, new_id, now_iso

bp = Blueprint('auth', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


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

    # In production: send verify_token by email
    # For now: log it so dev can verify manually
    import sys
    print(f'[AUTH] Verify token for {email}: {verify_token}', file=sys.stderr)

    resp = make_response(jsonify({
        'success': True,
        'user': {'id': uid, 'email': email, 'name': name, 'verified': False},
        'message': 'Account created. Check your email to verify.',
    }), 201)
    set_auth_cookie(resp, uid)
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
    set_auth_cookie(resp, row['id'])
    return resp


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
    uid = read_verify_token(token)
    if not uid:
        return jsonify({'error': 'Invalid or expired verification link'}), 400

    row = execute('SELECT id, verified FROM users WHERE id = ?', (uid,), fetchone=True)
    if not row:
        return jsonify({'error': 'User not found'}), 404
    if row['verified']:
        return jsonify({'message': 'Email already verified'}), 200

    execute('UPDATE users SET verified = 1, verify_token = NULL WHERE id = ?',
            (uid,), commit=True)
    return jsonify({'success': True, 'message': 'Email verified successfully'})


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
    return jsonify({'success': True, 'message': 'Password updated'})