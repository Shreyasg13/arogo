"""Sleep insights: bed/wake-time consistency metric."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "slp-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _logsleep(c, date, bedtime, wake, dur):
    c.post("/api/sleep", json={"date_key": date, "bedtime": bedtime,
                               "wake_time": wake, "duration_h": dur, "quality": 3})


def _ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_regular_schedule_reports_small_spread(app):
    c = _register(app, "slp1@medeasy.test")
    # Nearly identical bed/wake times every night → tiny spread.
    for i in range(5):
        _logsleep(c, _ago(i + 1), "23:00", "07:00", 8.0)
    s = c.get("/api/sleep/trend?days=30").get_json()["stats"]
    assert s["avg_bedtime"] == "23:00" and s["avg_waketime"] == "07:00"
    assert s["bedtime_spread"] == 0 and s["waketime_spread"] == 0


def test_irregular_schedule_reports_larger_spread(app):
    c = _register(app, "slp2@medeasy.test")
    beds  = ["22:00", "01:00", "23:30", "00:30", "22:30"]
    wakes = ["06:00", "09:00", "07:30", "08:00", "06:30"]
    for i in range(5):
        _logsleep(c, _ago(i + 1), beds[i], wakes[i], 8.0)
    s = c.get("/api/sleep/trend?days=30").get_json()["stats"]
    # Bedtimes span 22:00–01:00 (wrapping midnight) → a real, non-zero spread.
    assert s["bedtime_spread"] > 30
    assert s["waketime_spread"] > 30


def test_too_few_nights_gives_no_consistency(app):
    c = _register(app, "slp3@medeasy.test")
    _logsleep(c, _ago(1), "23:00", "07:00", 8.0)
    _logsleep(c, _ago(2), "23:15", "07:15", 8.0)      # only 2 nights (<3)
    s = c.get("/api/sleep/trend?days=30").get_json()["stats"]
    assert s["bedtime_spread"] is None and s["avg_bedtime"] is None
