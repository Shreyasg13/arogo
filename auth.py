"""
auth.py — Authentication layer for MedEasy Health OS

Pure-Python implementation using:
  - PBKDF2-HMAC-SHA256 (260k iterations) for password hashing
  - itsdangerous URLSafeTimedSerializer for signed session tokens
  - In-memory rate limiter (IP-based, resets after window)
  - HttpOnly cookie transport

Usage:
    from auth import require_auth, hash_password, check_password,
                     make_token, read_token
"""
from __future__ import annotations


import hashlib
import hmac
import os
import secrets
import time
from functools import wraps

from flask import g, jsonify, request, current_app
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# ── Constants ──────────────────────────────────────────────────────────────────
COOKIE_NAME    = 'me_session'
TOKEN_MAX_AGE  = 86400 * 7      # 7 days
PBKDF2_ITERS   = 260_000        # OWASP 2023 recommendation for SHA-256
SALT_BYTES     = 32

# Set COOKIE_SECURE=1 when serving over HTTPS (production)
COOKIE_SECURE  = os.environ.get('COOKIE_SECURE', '').lower() in ('1', 'true')

# ── Rate limiter (DB-backed, per IP) ──────────────────────────────────────────
# Stored in the auth_attempts table so the limit holds across multiple
# gunicorn workers (in-memory buckets were per-process).

RATE_LIMIT_MAX    = 10          # attempts
RATE_LIMIT_WINDOW = 60          # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited.
    Fails open if the DB is unavailable — auth still works, just unthrottled."""
    try:
        from db.core import execute
        now = time.time()
        execute("DELETE FROM auth_attempts WHERE ts < ?",
                (now - RATE_LIMIT_WINDOW,), commit=True)
        row = execute("SELECT COUNT(*) AS n FROM auth_attempts WHERE ip = ?",
                      (ip,), fetchone=True)
        if row and (row['n'] or 0) >= RATE_LIMIT_MAX:
            return False
        execute("INSERT INTO auth_attempts (ip, ts) VALUES (?, ?)",
                (ip, now), commit=True)
        return True
    except Exception:
        return True


def reset_rate_limiter():
    """Clear all recorded attempts (used by tests)."""
    try:
        from db.core import execute
        execute("DELETE FROM auth_attempts", commit=True)
    except Exception:
        pass


def rate_limit_auth(f):
    """Decorator: block IP after RATE_LIMIT_MAX auth attempts per window."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
        if not _check_rate_limit(ip):
            return jsonify({'error': 'Too many attempts. Try again in a minute.'}), 429
        return f(*args, **kwargs)
    return wrapper


# ── Password helpers ───────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return '{salt_hex}:{hash_hex}' using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(SALT_BYTES)
    h    = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PBKDF2_ITERS)
    return salt.hex() + ':' + h.hex()


def check_password(password: str, stored_hash: str) -> bool:
    """Constant-time comparison of password against stored hash."""
    try:
        salt_hex, hash_hex = stored_hash.split(':', 1)
        salt = bytes.fromhex(salt_hex)
        h    = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PBKDF2_ITERS)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


def validate_password_strength(password: str) -> str | None:
    """Return error string or None if valid."""
    if len(password) < 8:
        return 'Password must be at least 8 characters'
    if len(password) > 128:
        return 'Password too long'
    return None


# ── Token helpers (itsdangerous) ───────────────────────────────────────────────

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-session')


def _token_version(user_id: str) -> int:
    """Current token_version for a user — bumping it revokes all sessions."""
    from db.core import execute
    r = execute("SELECT token_version FROM users WHERE id=?", (user_id,), fetchone=True)
    return (r.get('token_version') or 0) if r else 0


def bump_token_version(user_id: str):
    """Invalidate every existing session token for this user."""
    from db.core import execute
    execute("UPDATE users SET token_version = COALESCE(token_version,0) + 1 WHERE id=?",
            (user_id,), commit=True)


def make_token(user_id: str) -> str:
    """Create a signed, time-stamped token carrying user_id + token version."""
    return _serializer().dumps({'uid': user_id, 'ver': _token_version(user_id)})


def read_token(token: str) -> str | None:
    """Verify token and return user_id, or None if invalid/expired/revoked."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
        uid = data.get('uid')
        # Tokens minted before a password change carry a stale version
        if uid is None or data.get('ver', 0) != _token_version(uid):
            return None
        return uid
    except (SignatureExpired, BadSignature, Exception):
        return None


def make_verify_token(user_id: str) -> str:
    """One-time email verification token (24h)."""
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-verify')
    return s.dumps({'uid': user_id})


def read_verify_token(token: str) -> str | None:
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-verify')
    try:
        data = s.loads(token, max_age=86400)
        return data.get('uid')
    except Exception:
        return None


def _secret_key() -> str:
    """SECRET_KEY from the app context, or Config directly outside one
    (scheduler jobs mint unsubscribe tokens without a request)."""
    try:
        return current_app.config['SECRET_KEY']
    except Exception:
        from config import Config
        return Config.SECRET_KEY


def make_digest_unsub_token(user_id: str) -> str:
    """Unsubscribe link token for weekly digest emails (90 days)."""
    s = URLSafeTimedSerializer(_secret_key(), salt='ms-digest')
    return s.dumps({'uid': user_id})


def read_digest_unsub_token(token: str) -> str | None:
    s = URLSafeTimedSerializer(_secret_key(), salt='ms-digest')
    try:
        data = s.loads(token, max_age=86400 * 90)
        return data.get('uid')
    except Exception:
        return None


def make_family_invite_token(invite_id: str) -> str:
    """Family invite token (72h) carrying the invite row id."""
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-family')
    return s.dumps({'iid': invite_id})


def read_family_invite_token(token: str) -> str | None:
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-family')
    try:
        data = s.loads(token, max_age=86400 * 3)
        return data.get('iid')
    except Exception:
        return None


def make_reset_token(user_id: str) -> str:
    """One-time password reset token (1h)."""
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-reset')
    return s.dumps({'uid': user_id})


def read_reset_token(token: str) -> str | None:
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='ms-reset')
    try:
        data = s.loads(token, max_age=3600)
        return data.get('uid')
    except Exception:
        return None


# ── Cookie helpers ─────────────────────────────────────────────────────────────

def set_auth_cookie(response, user_id: str):
    """Write session token as HttpOnly cookie."""
    token = make_token(user_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age   = TOKEN_MAX_AGE,
        httponly  = True,
        secure    = COOKIE_SECURE,   # COOKIE_SECURE=1 env when behind HTTPS
        samesite  = 'Lax',
        path      = '/',
    )
    return response


def clear_auth_cookie(response):
    response.delete_cookie(COOKIE_NAME, path='/')
    return response


def get_user_id_from_request() -> str | None:
    """Return the authenticated user_id, or None.

    Two transports, same signed token and revocation rules:
      - Authorization: Bearer <token>  (mobile / API clients)
      - me_session HttpOnly cookie     (the web app)
    """
    header = request.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        return read_token(header[7:].strip())
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return read_token(token)


# ── require_auth decorator ─────────────────────────────────────────────────────

def require_auth(f):
    """
    Route decorator: verify session cookie, inject g.user_id.
    Returns 401 JSON if unauthenticated.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'Authentication required', 'code': 'UNAUTHENTICATED'}), 401
        g.user_id = user_id
        return f(*args, **kwargs)
    return wrapper


# ── Security headers ───────────────────────────────────────────────────────────

# Strict script CSP: no 'unsafe-inline' — the frontend has no inline
# <script> blocks or on*= handler attributes. Interactivity runs through the
# data-ev-* dispatcher in app.js (see "CSP-safe event dispatch").
# style-src keeps 'unsafe-inline' for the style="" attributes used across
# the markup — far lower risk than inline script.
# Disable with CSP_ENABLED=0 if it ever gets in the way during development.
CSP_ENABLED = os.environ.get('CSP_ENABLED', '1') == '1'
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https://upload.wikimedia.org; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)


def add_security_headers(response):
    """Add security headers to every response."""
    response.headers['X-Frame-Options']        = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
    if CSP_ENABLED:
        response.headers['Content-Security-Policy'] = CSP_POLICY
    if COOKIE_SECURE:
        # Only meaningful over HTTPS — enabled together with the secure cookie
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response