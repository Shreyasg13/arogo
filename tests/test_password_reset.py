"""
tests/test_password_reset.py — Email verification + password reset flows.

Outbound email is captured by monkeypatching mailer.send_email, so these
tests exercise the real token round-trip without an SMTP server.

Run:  pytest tests/test_password_reset.py -v
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

EMAIL  = "resetme@medeasy.test"
PW_OLD = "old-password-123"
PW_NEW = "new-password-456"


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    """These tests hammer auth routes; don't let the IP limiter interfere."""
    auth_module._rate_buckets.clear()
    yield
    auth_module._rate_buckets.clear()


@pytest.fixture()
def sent(monkeypatch):
    """Capture outbound emails instead of sending them."""
    box = []
    monkeypatch.setattr(
        mailer, "send_email",
        lambda to, subject, text: box.append({"to": to, "subject": subject, "text": text}) or True)
    return box


def _extract(pattern, box):
    for m in box:
        found = re.search(pattern, m["text"])
        if found:
            return found.group(1)
    return None


class TestVerificationEmail:
    def test_register_sends_verification_and_link_works(self, app, sent):
        c = app.test_client()
        r = c.post("/auth/register", json={"email": EMAIL, "password": PW_OLD})
        assert r.status_code == 201
        token = _extract(r"/auth/verify/(\S+)", sent)
        assert token, "no verification email captured"
        assert c.get(f"/auth/verify/{token}").status_code == 200
        me = c.get("/auth/me").get_json()
        assert me["verified"] is True


class TestForgotPassword:
    def test_unknown_email_still_returns_success(self, app, sent):
        c = app.test_client()
        r = c.post("/auth/forgot-password", json={"email": "nobody@medeasy.test"})
        assert r.status_code == 200 and r.get_json()["success"]
        assert not sent, "must not send email for unknown accounts"

    def test_invalid_email_rejected(self, app):
        c = app.test_client()
        assert c.post("/auth/forgot-password",
                      json={"email": "not-an-email"}).status_code == 400

    def test_full_reset_flow(self, app, sent):
        c = app.test_client()
        r = c.post("/auth/forgot-password", json={"email": EMAIL})
        assert r.status_code == 200
        token = _extract(r"\?reset=(\S+)", sent)
        assert token, "no reset email captured"

        r = c.post("/auth/reset-password", json={"token": token, "password": PW_NEW})
        assert r.status_code == 200 and r.get_json()["success"]

        # Old password no longer works, new one does
        assert c.post("/auth/login",
                      json={"email": EMAIL, "password": PW_OLD}).status_code == 401
        assert c.post("/auth/login",
                      json={"email": EMAIL, "password": PW_NEW}).status_code == 200

    def test_reset_revokes_existing_sessions(self, app, sent):
        """A stolen/old session cookie must die when the password is reset."""
        email = "revoke-me@medeasy.test"
        old_session = app.test_client()
        r = old_session.post("/auth/register", json={"email": email, "password": PW_OLD})
        assert r.status_code == 201
        assert old_session.get("/auth/me").status_code == 200

        # Reset the password from a different client
        other = app.test_client()
        other.post("/auth/forgot-password", json={"email": email})
        token = _extract(r"\?reset=(\S+)", sent)
        assert other.post("/auth/reset-password",
                          json={"token": token, "password": PW_NEW}).status_code == 200

        # The pre-reset session is now invalid; a fresh login works
        assert old_session.get("/auth/me").status_code == 401
        assert old_session.post("/auth/login",
                                json={"email": email, "password": PW_NEW}).status_code == 200
        assert old_session.get("/auth/me").status_code == 200

    def test_reset_rejects_garbage_token(self, app):
        c = app.test_client()
        r = c.post("/auth/reset-password",
                   json={"token": "garbage", "password": "whatever-123"})
        assert r.status_code == 400

    def test_reset_rejects_weak_password(self, app, sent):
        c = app.test_client()
        c.post("/auth/forgot-password", json={"email": EMAIL})
        token = _extract(r"\?reset=(\S+)", sent)
        r = c.post("/auth/reset-password", json={"token": token, "password": "short"})
        assert r.status_code == 400
