"""
tests/test_digest.py — Weekly digest: API shape, email job, unsubscribe.

Run:  pytest tests/test_digest.py -v
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

EMAIL = "digest@medeasy.test"
PW = "digest-pw-12345"


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


@pytest.fixture()
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(
        mailer, "send_email",
        lambda to, subject, text: box.append({"to": to, "subject": subject, "text": text}) or True)
    return box


@pytest.fixture(scope="module")
def user(app):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": EMAIL, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code in (200, 201)
    return c


class TestDigestApi:
    def test_shape(self, user):
        d = user.get("/api/weekly-digest").get_json()
        assert d["overall_score"] >= 0
        assert d["headline"]
        assert "period_label" in d          # portable strftime (no %-d)
        for k in ["sleep", "workouts", "habits", "hydration", "nutrition"]:
            assert k in d["scores"]

    def test_no_data_week_is_not_scored_as_failure(self, app):
        # A brand-new user with nothing logged must get a welcoming headline,
        # never the demoralising "Tough week …" that 0/5 would otherwise pick.
        auth_module.reset_rate_limiter()
        c = app.test_client()
        c.post("/auth/register",
               json={"email": "empty-digest@medeasy.test", "password": PW})
        d = c.get("/api/weekly-digest").get_json()
        assert d["overall_score"] == 0
        assert "Tough week" not in d["headline"]
        assert "Nothing logged yet" in d["headline"]


class TestDigestEmailJob:
    def test_sends_once_per_week(self, app, user, sent):
        from scheduler import _send_weekly_digests
        _send_weekly_digests()
        mine = [m for m in sent if m["to"] == EMAIL]
        assert len(mine) == 1, "digest email not sent"
        assert "Arogo week" in mine[0]["subject"]
        assert "/api/digest/unsubscribe/" in mine[0]["text"]

        # Second run within the same week: deduped, no second email
        _send_weekly_digests()
        assert len([m for m in sent if m["to"] == EMAIL]) == 1

    def test_unsubscribe_link_works(self, app, user, sent):
        from scheduler import _send_weekly_digests
        from db.core import execute
        # Reset dedupe so a fresh digest (with link) is generated
        execute("DELETE FROM notification_log WHERE type='digest_email'", commit=True)
        _send_weekly_digests()
        mine = [m for m in sent if m["to"] == EMAIL]
        token = re.search(r"/api/digest/unsubscribe/(\S+)", mine[-1]["text"]).group(1)

        anon = app.test_client()
        r = anon.get(f"/api/digest/unsubscribe/{token}")
        assert r.status_code == 200 and b"unsubscribed" in r.data

        settings = user.get("/api/reminders/settings").get_json()
        assert settings["weekly_digest_enabled"] == 0

        # No more digest emails after opting out
        execute("DELETE FROM notification_log WHERE type='digest_email'", commit=True)
        sent.clear()
        _send_weekly_digests()
        assert not [m for m in sent if m["to"] == EMAIL]

    def test_garbage_unsub_token_rejected(self, app):
        r = app.test_client().get("/api/digest/unsubscribe/garbage")
        assert r.status_code == 400
