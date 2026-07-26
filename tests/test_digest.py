"""
tests/test_digest.py — Weekly digest: API shape, email job, unsubscribe.

Run:  pytest tests/test_digest.py -v
"""
import datetime as dt
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
        # None is a legitimate score: it means "nothing to score yet".
        assert d["overall_score"] is None or d["overall_score"] >= 0
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
        # Not 0 — a zero says "you failed at everything" where the truth is
        # "you haven't tracked anything". None lets the UI omit the ring
        # instead of drawing a red 0 under "Nothing logged yet".
        assert d["overall_score"] is None
        assert d["tracked_areas"] == 0
        assert "Tough week" not in d["headline"]
        assert "Nothing logged yet" in d["headline"]
        # …and it must not complain about features they've never used.
        assert d["concerns"] == []

    def test_untracked_areas_are_absences_not_zeros(self, app):
        """Someone who sleeps well and ignores the rest of the app had every
        untracked category scored as 0 and divided by 5 — so 8h a night became
        (100+0+0+0+0)/5 = 20/100 and an email headed "Tough week". Not using a
        feature is not a failure to report back to someone."""
        auth_module.reset_rate_limiter()
        c = app.test_client()
        c.post("/auth/register",
               json={"email": "sleeper-digest@medeasy.test", "password": PW})
        # Log the last 7 nights relative to today so the entries always land
        # inside the digest's rolling 7-day window (was hardcoded July dates,
        # which silently aged out of the window and failed after any rollover).
        today = dt.date.today()
        for offset in range(7):
            wake = today - dt.timedelta(days=offset)
            bed = wake - dt.timedelta(days=1)
            c.post("/api/sleep", json={
                "date_key": wake.isoformat(),
                "bedtime": f"{bed.isoformat()}T23:00",
                "wake_time": f"{wake.isoformat()}T07:00", "quality": 4})

        d = c.get("/api/weekly-digest").get_json()
        assert d["scores"]["sleep"] is not None, "sleep was tracked; score it"
        for untracked in ("workouts", "habits", "hydration", "nutrition"):
            assert d["scores"][untracked] is None, \
                f"{untracked} isn't tracked — it must be absent, not 0"
        assert d["tracked_areas"] == 1
        assert d["overall_score"] == d["scores"]["sleep"], \
            "the score must average only what's tracked"
        assert "Tough week" not in d["headline"]


class TestDigestHonesty:
    def test_feed_does_not_claim_emailed_when_smtp_is_unconfigured(self, app, monkeypatch):
        """mailer.send_*() returns True after merely printing to stderr when
        SMTP_HOST is unset, so a deploy missing SMTP would tell every user
        their digest was emailed, every week, while sending nothing. The digest
        is readable in-app either way — "ready" is the true word for that."""
        import mailer
        import scheduler

        monkeypatch.setattr(mailer, "is_configured", lambda: False)
        assert "emailed" not in scheduler._digest_log_title("Weekly digest")
        assert scheduler._digest_log_title("Weekly digest") == "Weekly digest ready"

        monkeypatch.setattr(mailer, "is_configured", lambda: True)
        assert scheduler._digest_log_title("Weekly digest") == "Weekly digest emailed"


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
