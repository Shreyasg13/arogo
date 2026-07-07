"""
tests/test_push.py — Web Push: subscription endpoints + server reminder engine.

Real push delivery needs a browser + push service; here we capture
push.push_to_user to verify the reminder logic end to end.

Run:  pytest tests/test_push.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import datetime
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
import push as push_module
from db.core import init_db, execute
from app import create_app

EMAIL = "push@medeasy.test"
PW = "push-pw-123456"

FAKE_SUB = {
    "endpoint": "https://push.example.com/sub/abc123",
    "keys": {"p256dh": "fake-p256dh-key", "auth": "fake-auth"},
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


@pytest.fixture(scope="module")
def user(app):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": EMAIL, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code in (200, 201)
    return c


class TestSubscriptionEndpoints:
    def test_vapid_key_available(self, user):
        d = user.get("/api/push/vapid-public-key").get_json()
        assert d["enabled"] is True and d["key"]

    def test_subscribe_and_unsubscribe(self, user):
        r = user.post("/api/push/subscribe", json={"subscription": FAKE_SUB})
        assert r.status_code == 200
        row = execute("SELECT * FROM push_subscriptions WHERE endpoint=?",
                      (FAKE_SUB["endpoint"],), fetchone=True)
        assert row is not None

        r = user.post("/api/push/unsubscribe", json={"endpoint": FAKE_SUB["endpoint"]})
        assert r.status_code == 200
        assert execute("SELECT * FROM push_subscriptions WHERE endpoint=?",
                       (FAKE_SUB["endpoint"],), fetchone=True) is None

    def test_invalid_subscription_rejected(self, user):
        assert user.post("/api/push/subscribe",
                         json={"subscription": {"endpoint": ""}}).status_code == 400

    def test_requires_auth(self, app):
        assert app.test_client().post(
            "/api/push/subscribe", json={"subscription": FAKE_SUB}).status_code == 401


class TestReminderEngine:
    @pytest.fixture()
    def delivered(self, monkeypatch):
        box = []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, title, body, url='/': box.append(
                                {"uid": uid, "title": title, "body": body}) or 1)
        return box

    def test_due_dose_triggers_push_once(self, app, user, delivered):
        from scheduler import _push_reminders

        # Subscribed user with a medicine due right now
        user.post("/api/push/subscribe", json={"subscription": FAKE_SUB})
        now_hhmm = datetime.datetime.now().strftime("%H:%M")
        r = user.post("/api/medicines", json={
            "name": "PushPill", "dosage": "5", "times": [now_hhmm]})
        assert r.status_code == 200

        _push_reminders()
        pushes = [p for p in delivered if "PushPill" in p["title"]]
        assert len(pushes) == 1, f"expected one dose push, got {delivered}"

        # Re-running within the same window must not re-notify
        _push_reminders()
        assert len([p for p in delivered if "PushPill" in p["title"]]) == 1

    def test_taken_dose_not_notified(self, app, user, delivered):
        from scheduler import _push_reminders

        now_hhmm = datetime.datetime.now().strftime("%H:%M")
        r = user.post("/api/medicines", json={
            "name": "TakenPill", "dosage": "5", "times": [now_hhmm]})
        mid = r.get_json()["medicine"]["id"]
        user.post(f"/api/medicines/{mid}/log",
                  json={"time": now_hhmm, "taken": True})

        _push_reminders()
        assert not [p for p in delivered if "TakenPill" in p["title"]]
