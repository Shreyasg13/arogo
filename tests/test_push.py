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
TODAY = datetime.date.today().isoformat()
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
                            lambda uid, title, body, url='/', actions=None: box.append(
                                {"uid": uid, "title": title, "body": body,
                                 "actions": actions}) or 1)
        return box

    def test_due_dose_triggers_push_once(self, app, user, delivered):
        from scheduler import _push_reminders

        # Subscribed user with a medicine due right now
        user.post("/api/push/subscribe", json={"subscription": FAKE_SUB})
        now_hhmm = datetime.datetime.now().strftime("%H:%M")
        r = user.post("/api/medicines", json={
            "name": "PushPill", "dosage": "5", "times": [now_hhmm]})
        assert r.status_code == 200
        mid = r.get_json()["medicine"]["id"]

        _push_reminders()
        pushes = [p for p in delivered if "PushPill" in p["title"]]
        assert len(pushes) == 1, f"expected one dose push, got {delivered}"

        # …and it carries a one-tap "✓ Taken" button (the core adherence loop
        # shouldn't need an app open), plus a snooze.
        acts = pushes[0]["actions"]
        assert acts, "dose reminder must carry a quick-log action"
        assert acts[0]["action"] == f"dose-{mid}-{now_hhmm}"
        assert any(a["action"] == "snooze" for a in acts)

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


class TestWaterQuickLog:
    """The hydration reminder carries action buttons so the user can log water
    straight from the notification, using their real usual pour."""

    @pytest.fixture()
    def delivered(self, monkeypatch):
        box = []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, title, body, url='/', actions=None: box.append(
                                {"uid": uid, "title": title, "body": body,
                                 "actions": actions}) or 1)
        return box

    def test_usual_sip_learns_the_users_container(self, app, user):
        import scheduler
        from db.core import user_context
        uid = execute("SELECT id FROM users WHERE email=?", (EMAIL,), fetchone=True)["id"]
        execute("DELETE FROM hydration_logs WHERE user_id=?", (uid,), commit=True)

        # No history yet → safe default
        assert scheduler._usual_sip_ml(uid) == 250

        # They actually drink from a 750ml bottle (most often), plus a stray 200
        from db import log_hydration, today_iso
        with user_context(uid):
            for _ in range(3):
                log_hydration(750, "water", today_iso())
            log_hydration(200, "water", today_iso())
        assert scheduler._usual_sip_ml(uid) == 750   # by frequency, not size/recency

    def test_tapping_the_suggested_amount_does_not_teach_it_back_to_us(self, app, user):
        """The reminder's button offers usual_sip_ml, and the tap writes it
        back. If that counted as a deliberate choice, the app's own made-up
        250ml default would be laundered into "what they drink" and keep
        outvoting the real bottle they log by hand — the feature defeating its
        own stated purpose, self-reinforcingly."""
        import scheduler
        uid = execute("SELECT id FROM users WHERE email=?", (EMAIL,), fetchone=True)["id"]
        execute("DELETE FROM hydration_logs WHERE user_id=?", (uid,), commit=True)

        # Cold start: the app suggests 250 because it knows nothing.
        assert scheduler._usual_sip_ml(uid) == 250

        # They tap that suggestion five times — the service worker's exact POST.
        for _ in range(5):
            r = user.post("/api/hydration", json={
                "amount_ml": 250, "drink_type": "water",
                "date_key": TODAY, "source": "notification"})
            assert r.status_code == 200

        # …and deliberately log their real 500ml bottle four times in-app.
        for _ in range(4):
            user.post("/api/hydration", json={"amount_ml": 500, "drink_type": "water",
                                              "date_key": TODAY})

        assert scheduler._usual_sip_ml(uid) == 500, (
            "the app's own suggested default outvoted the container the user "
            "actually chose")
        # The water still counts toward the day — it was drunk either way.
        total = execute("SELECT SUM(amount_ml) AS t FROM hydration_logs WHERE user_id=?",
                        (uid,), fetchone=True)["t"]
        assert total == 5 * 250 + 4 * 500

    def test_hydration_rejects_a_garbage_date(self, app, user):
        """A bogus date_key orphans the log on a day the UI can't navigate to,
        where it counts toward no total and can't be deleted. The food route
        already rejected this; hydration was the gap."""
        assert user.post("/api/hydration",
                         json={"amount_ml": 250, "date_key": "tomorrow"}).status_code == 400

    def test_mood_reminder_can_be_answered_from_the_notification(self, app, user, delivered, monkeypatch):
        import scheduler
        from db.core import user_context, execute as ex
        uid = ex("SELECT id FROM users WHERE email=?", (EMAIL,), fetchone=True)["id"]
        user.post("/api/push/subscribe", json={"subscription": FAKE_SUB})
        user.get("/api/reminders/settings")
        ex("DELETE FROM notification_log WHERE user_id=?", (uid,), commit=True)

        # Pretend it's exactly the configured mood-reminder time
        rs = user.get("/api/reminders/settings").get_json()
        h, m = (rs.get("mood_reminder_time") or "18:00").split(":")
        monkeypatch.setattr(scheduler, "_user_local_now",
                            lambda u: datetime.datetime.combine(
                                datetime.date.today(), datetime.time(int(h), int(m))))
        with user_context(uid):
            scheduler._push_reminders_for_user(uid)

        mood = [p for p in delivered if "How was your day" in p["title"]]
        assert mood, f"expected the mood nudge, got {[p['title'] for p in delivered]}"
        acts = mood[0]["actions"]
        assert acts, "mood nudge should be answerable from the notification"
        # The two that matter: fine vs not-fine (keys match the app's CI_MOODS)
        assert {a["action"] for a in acts} == {"mood-happy", "mood-sad"}

    def test_hydration_reminder_has_quick_log_buttons(self, app, user, delivered, monkeypatch):
        import scheduler
        from db.core import user_context
        uid = execute("SELECT id FROM users WHERE email=?", (EMAIL,), fetchone=True)["id"]
        user.post("/api/push/subscribe", json={"subscription": FAKE_SUB})
        user.get("/api/reminders/settings")     # creates defaults (water_enabled=1)
        execute("DELETE FROM hydration_logs WHERE user_id=?", (uid,), commit=True)
        execute("DELETE FROM notification_log WHERE user_id=?", (uid,), commit=True)

        # Behind pace late in the day → reminder fires
        from db import log_hydration, today_iso
        with user_context(uid):
            log_hydration(500, "water", today_iso())
        monkeypatch.setattr(scheduler, "_user_local_now",
                            lambda u: datetime.datetime.combine(
                                datetime.date.today(), datetime.time(19, 0)))

        with user_context(uid):
            scheduler._push_reminders_for_user(uid)

        water = [p for p in delivered if "Hydration" in p["title"]]
        assert water, f"expected a hydration reminder, got {delivered}"
        acts = water[0]["actions"]
        assert acts, "hydration reminder must carry quick-log action buttons"
        # Button offers their real pour (500), not a hardcoded 250, + a snooze
        assert acts[0]["action"] == "water-500"
        assert any(a["action"] == "snooze" for a in acts)
