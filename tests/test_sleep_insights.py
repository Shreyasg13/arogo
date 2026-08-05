"""Sleep debt (shortfall vs target) & bedtime consistency (spread of bedtimes)."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.wellness import (log_sleep, get_sleep_target, set_sleep_target,
                         get_sleep_insights, _bedtime_offset_min)

PW = "sl-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def _night(day_offset, bed_hhmm, wake_hhmm):
    """Build a sleep-log payload for a night N days ago. bed on the evening
    before the wake date so durations are realistic."""
    wake_date = dt.date.today() - dt.timedelta(days=day_offset)
    bed_date = wake_date - dt.timedelta(days=1)
    return {"bedtime": f"{bed_date.isoformat()}T{bed_hhmm}",
            "wake_time": f"{wake_date.isoformat()}T{wake_hhmm}",
            "quality": 3}


def test_target_set_get_clear(app):
    _, uid = _uid(app, "sl1@medeasy.test")
    with user_context(uid):
        assert get_sleep_target() is None            # never invented
        assert set_sleep_target(8) == 8.0
        assert get_sleep_target() == 8.0
        assert set_sleep_target(99) == 14.0          # clamped to sane band
        assert set_sleep_target(0) is None           # 0 clears
        assert get_sleep_target() is None


def test_no_target_no_debt(app):
    _, uid = _uid(app, "sl2@medeasy.test")
    with user_context(uid):
        log_sleep(_night(1, "23:00", "06:00"))       # 7 h
        ins = get_sleep_insights()
        assert ins["has_data"] is True
        assert ins["avg_duration_h"] == 7.0
        assert ins["debt_h"] is None                 # no target → no debt figure


def test_debt_counts_only_shortfalls(app):
    _, uid = _uid(app, "sl3@medeasy.test")
    with user_context(uid):
        set_sleep_target(8)
        log_sleep(_night(1, "23:00", "06:00"))       # 7 h → 1 h short
        log_sleep(_night(2, "23:00", "05:00"))       # 6 h → 2 h short
        log_sleep(_night(3, "22:00", "08:00"))       # 10 h → surplus, no credit
        ins = get_sleep_insights()
        assert ins["target_h"] == 8.0
        assert ins["debt_h"] == 3.0                  # 1 + 2, lie-in doesn't erase it
        assert ins["short_nights"] == 2


def test_bedtime_offset_wraps_around_midnight(app):
    # 23:30 and 00:30 are one hour apart on the 6pm-anchored scale.
    assert _bedtime_offset_min("2026-08-01T23:30") == (23 * 60 + 30) - 18 * 60
    assert _bedtime_offset_min("2026-08-01T00:30") == ((0 * 60 + 30) - 18 * 60) % 1440
    a = _bedtime_offset_min("2026-08-01T23:30")
    b = _bedtime_offset_min("2026-08-02T00:30")
    assert abs(a - b) == 60


def test_consistency_needs_three_nights(app):
    _, uid = _uid(app, "sl4@medeasy.test")
    with user_context(uid):
        log_sleep(_night(1, "23:00", "07:00"))
        log_sleep(_night(2, "23:15", "07:00"))
        assert get_sleep_insights()["consistency_min"] is None   # <3 nights
        log_sleep(_night(3, "22:45", "07:00"))
        ins = get_sleep_insights()
        assert ins["consistency_min"] is not None
        assert ins["consistency_min"] < 30           # tight cluster → small spread
        assert ins["typical_bedtime"] == "23:00"


def test_isolation(app):
    _, uid_a = _uid(app, "sl5@medeasy.test")
    _, uid_b = _uid(app, "sl6@medeasy.test")
    with user_context(uid_a):
        set_sleep_target(8)
        log_sleep(_night(1, "23:00", "05:00"))
    with user_context(uid_b):
        ins = get_sleep_insights()
        assert ins["has_data"] is False
        assert ins["target_h"] is None


def test_api_round_trip(app):
    c, uid = _uid(app, "sl7@medeasy.test")
    assert c.post("/api/sleep/target", json={"hours": 7.5}).get_json()["target_h"] == 7.5
    assert c.get("/api/sleep/target").get_json()["target_h"] == 7.5
    c.post("/api/sleep", json=_night(1, "00:30", "06:30"))    # 6 h → 1.5 short
    ins = c.get("/api/sleep/insights").get_json()
    assert ins["debt_h"] == 1.5
