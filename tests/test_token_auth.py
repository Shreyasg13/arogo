"""
tests/test_token_auth.py — Bearer-token auth + /api/v1 aliases
(the backend pre-work for the native mobile app).

Run:  pytest tests/test_token_auth.py -v
"""
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

EMAIL = "mobile@medeasy.test"
PW = "mobile-pw-12345"
PW2 = "mobile-pw-67890"


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


@pytest.fixture(scope="module")
def token(app):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": EMAIL, "password": PW})
    assert r.status_code in (200, 201, 409)
    r = c.post("/auth/token", json={"email": EMAIL, "password": PW})
    assert r.status_code == 200
    d = r.get_json()
    assert d["token_type"] == "Bearer" and d["expires_in"] > 0
    return d["token"]


def _bearer(app, token):
    """A cookie-less client that authenticates via header only."""
    c = app.test_client(use_cookies=False)
    c.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return c


class TestTokenIssue:
    def test_wrong_password_rejected(self, app, token):
        r = app.test_client().post("/auth/token",
                                   json={"email": EMAIL, "password": "wrong-pw-123"})
        assert r.status_code == 401

    def test_unknown_email_rejected(self, app):
        r = app.test_client().post("/auth/token",
                                   json={"email": "ghost@medeasy.test", "password": PW})
        assert r.status_code == 401


class TestBearerAccess:
    def test_bearer_works_without_cookies(self, app, token):
        c = _bearer(app, token)
        me = c.get("/auth/me")
        assert me.status_code == 200 and me.get_json()["email"] == EMAIL
        assert c.get("/api/medicines").status_code == 200

    def test_garbage_bearer_rejected(self, app):
        c = _bearer(app, "garbage-token")
        assert c.get("/auth/me").status_code == 401

    def test_bearer_scopes_data_per_user(self, app, token):
        c = _bearer(app, token)
        r = c.post("/api/medicines", json={"name": "BearerPill", "dosage": "1"})
        assert r.status_code == 200
        # a different client with no auth sees nothing
        assert app.test_client(use_cookies=False).get("/api/medicines").status_code == 401


class TestV1Aliases:
    def test_v1_api_alias(self, app, token):
        c = _bearer(app, token)
        assert c.get("/api/v1/medicines").status_code == 200
        assert c.get("/api/v1/auth/me").get_json()["email"] == EMAIL

    def test_v1_token_issue(self, app):
        r = app.test_client().post("/api/v1/auth/token",
                                   json={"email": EMAIL, "password": PW})
        assert r.status_code == 200 and r.get_json()["token"]

    def test_v1_unknown_route_is_json_404(self, app, token):
        r = _bearer(app, token).get("/api/v1/does-not-exist")
        assert r.status_code == 404
        assert r.get_json()["error"] == "Route not found"


class TestRevocation:
    def test_password_reset_kills_bearer_tokens(self, app, token, monkeypatch):
        box = []
        monkeypatch.setattr(mailer, "send_email",
                            lambda to, s, t: box.append(t) or True)
        c = _bearer(app, token)
        assert c.get("/auth/me").status_code == 200

        anon = app.test_client()
        anon.post("/auth/forgot-password", json={"email": EMAIL})
        reset = re.search(r"\?reset=(\S+)", box[-1]).group(1)
        r = anon.post("/auth/reset-password", json={"token": reset, "password": PW2})
        assert r.status_code == 200

        assert c.get("/auth/me").status_code == 401, \
            "bearer token survived a password reset"
