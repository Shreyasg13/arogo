"""
tests/test_security.py — Endpoint security sweep + data privacy guarantees.

The centerpiece is TestAuthSweep: it enumerates EVERY route in the app
(including /api/v1 aliases) and asserts that anything not on the
explicit public allowlist rejects unauthenticated requests. A new
endpoint added without @require_auth fails this suite automatically.

Run:  pytest tests/test_security.py -v
"""
import io
import os
os.environ["MEDEASY_DB"] = ":memory:"

import re
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
import mailer
from db.core import init_db
from app import create_app

PW = "security-pw-12345"

# Routes that are INTENTIONALLY reachable without a session.
# Everything else must 401. Keep this list short and deliberate.
PUBLIC_ROUTES = {
    '/',                                # SPA shell (auth screen)
    '/sw.js',                           # service worker
    '/.well-known/security.txt',        # RFC 9116 disclosure contact (public by design)
    '/auth/register',
    '/auth/login',
    '/auth/token',
    '/auth/logout',                     # clearing a cookie needs no auth
    '/auth/verify/<token>',             # token-gated by signature
    '/auth/forgot-password',
    '/auth/reset-password',             # token-gated by signature
    '/api/digest/unsubscribe/<token>',  # token-gated by signature
    '/api/caregiver-digest/unsubscribe/<token>',  # token-gated by signature
}


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


def _user(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201)
    return c


def _is_public(rule: str) -> bool:
    base = rule[len('/api/v1'):] if rule.startswith('/api/v1/') else rule
    if not base.startswith('/'):
        base = '/' + base
    return (rule in PUBLIC_ROUTES or base in PUBLIC_ROUTES
            or ('/api' + base) in PUBLIC_ROUTES
            or rule.startswith('/static/'))


class TestAuthSweep:
    def test_every_route_requires_auth_or_is_allowlisted(self, app):
        anon = app.test_client()
        failures = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static' or _is_public(rule.rule):
                continue
            path = re.sub(r'<[^>]+>', 'sweep-test-id', rule.rule)
            methods = rule.methods - {'HEAD', 'OPTIONS'}
            for method in methods:
                resp = anon.open(path, method=method,
                                 json={} if method in ('POST', 'PUT', 'PATCH') else None)
                if resp.status_code != 401:
                    failures.append(f"{method} {rule.rule} → {resp.status_code}")
        assert not failures, (
            "Unauthenticated access NOT rejected on:\n  " + "\n  ".join(sorted(failures)))

    def test_sweep_covers_a_sane_number_of_routes(self, app):
        protected = [r for r in app.url_map.iter_rules()
                     if r.endpoint != 'static' and not _is_public(r.rule)]
        assert len(protected) > 250, "route sweep suspiciously small — check _is_public"


class TestMedicalFilePrivacy:
    def test_upload_download_owner_only(self, app):
        alice = _user(app, "file-alice@medeasy.test")
        bob = _user(app, "file-bob@medeasy.test")

        r = alice.post("/api/upload", data={
            "file": (io.BytesIO(b"%PDF-1.4 fake blood report"), "blood_test.pdf"),
            "patient_name": "Alice", "report_type": "Blood Test",
        }, content_type="multipart/form-data")
        assert r.status_code == 200, r.get_json()
        fname = r.get_json()["report"]["filename"]

        # Owner can download
        assert alice.get(f"/uploads/{fname}").status_code == 200
        # A DIFFERENT logged-in user cannot (IDOR)
        assert bob.get(f"/uploads/{fname}").status_code == 404, \
            "another user could download Alice's medical file"
        # Anonymous cannot
        assert app.test_client().get(f"/uploads/{fname}").status_code == 401

    def test_disallowed_file_type_rejected(self, app):
        alice = _user(app, "file-alice@medeasy.test")
        r = alice.post("/api/upload", data={
            "file": (io.BytesIO(b"MZ fake exe"), "malware.exe"),
        }, content_type="multipart/form-data")
        assert r.status_code == 400

    def test_path_traversal_blocked(self, app):
        alice = _user(app, "file-alice@medeasy.test")
        for attempt in ["..%2Fapp.py", "..%5Capp.py", "%2e%2e%2fconfig.py"]:
            r = alice.get(f"/uploads/{attempt}")
            assert r.status_code in (400, 404), f"traversal not blocked: {attempt}"

    def test_bob_cannot_delete_alices_report(self, app):
        alice = _user(app, "file-alice@medeasy.test")
        bob = _user(app, "file-bob@medeasy.test")
        r = alice.post("/api/upload", data={
            "file": (io.BytesIO(b"data"), "scan.pdf"),
        }, content_type="multipart/form-data")
        rid = r.get_json()["report"]["id"]
        assert bob.delete(f"/api/reports/{rid}").status_code == 404
        assert any(x["id"] == rid for x in alice.get("/api/reports").get_json())


class TestTokenHygiene:
    def test_reset_token_is_single_use(self, app, monkeypatch):
        box = []
        monkeypatch.setattr(mailer, "send_email", lambda to, s, t: box.append(t) or True)
        email = "singleuse@medeasy.test"
        c = _user(app, email)

        c.post("/auth/forgot-password", json={"email": email})
        token = re.search(r"\?reset=(\S+)", box[-1]).group(1)

        r = c.post("/auth/reset-password", json={"token": token, "password": "new-pass-12345"})
        assert r.status_code == 200
        # Replaying the same token must fail
        r = c.post("/auth/reset-password", json={"token": token, "password": "evil-pass-12345"})
        assert r.status_code == 400, "reset token was replayable"

    def test_session_cookie_flags(self, app):
        c = app.test_client()
        r = c.post("/auth/register", json={"email": "cookie@medeasy.test", "password": PW})
        cookie = r.headers.get("Set-Cookie", "")
        assert "HttpOnly" in cookie
        assert "SameSite=Lax" in cookie


class TestInjectionSmoke:
    def test_search_survives_sql_metacharacters(self, app):
        c = _user(app, "inject@medeasy.test")
        for payload in ["'; DROP TABLE users;--", "%' OR '1'='1", 'a"b`c']:
            r = c.get("/api/search", query_string={"q": payload})
            assert r.status_code == 200, payload
        # users table still alive
        assert c.get("/auth/me").status_code == 200

    def test_export_sections_param_is_safe(self, app):
        c = _user(app, "inject@medeasy.test")
        r = c.get("/api/export", query_string={
            "format": "json", "sections": "users;DROP TABLE users,--"})
        assert r.status_code == 200
        assert c.get("/auth/me").status_code == 200
