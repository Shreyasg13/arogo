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
from collections import defaultdict
from functools import wraps

from flask import g, jsonify, request, current_app
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# ── Constants ──────────────────────────────────────────────────────────────────
COOKIE_NAME    = 'ms_session'
TOKEN_MAX_AGE  = 86400 * 7      # 7 days
PBKDF2_ITERS   = 260_000        # OWASP 2023 recommendation for SHA-256
SALT_BYTES     = 32

# ── Rate limiter (in-memory, per IP) ──────────────────────────────────────────
# { ip: [timestamp, timestamp, ...] }
_rate_buckets: dict[str, list[float]] = defaultdict(list)

RATE_LIMIT_MAX    = 10          # attempts
RATE_LIMIT_WINDOW = 60          # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    bucket = _rate_buckets[ip]
    # Drop old entries outside the window
    _rate_buckets[ip] = [t for t in bucket if t > window_start]
    if len(_rate_buckets[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_buckets[ip].append(now)
    return True


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


def make_token(user_id: str) -> str:
    """Create a signed, time-stamped token carrying user_id."""
    return _serializer().dumps({'uid': user_id})


def read_token(token: str) -> str | None:
    """Verify token and return user_id, or None if invalid/expired."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
        return data.get('uid')
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
        secure    = False,   # set True in production (HTTPS only)
        samesite  = 'Lax',
        path      = '/',
    )
    return response


def clear_auth_cookie(response):
    response.delete_cookie(COOKIE_NAME, path='/')
    return response


def get_user_id_from_request() -> str | None:
    """Read and verify the session cookie. Return user_id or None."""
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

def add_security_headers(response):
    """Add security headers to every response."""
    response.headers['X-Frame-Options']        = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
    # NOTE: CSP intentionally omitted during development — add back for production
    # with a proper nonce-based policy once the app is stable.
    return response