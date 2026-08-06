"""Two-metric correlation explorer — honest move-together / opposite / no-link."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.metric_insights import get_metric_correlation, get_correlatable_metrics
from db.health import log_vital
from db.wellness import log_sleep

PW = "corr-pw-12345"


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


def _day(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_not_enough_shared_days(app):
    _, uid = _uid(app, "corr1@medeasy.test")
    with user_context(uid):
        for i in range(3):
            log_vital({"type": "heart_rate", "value1": 70 + i, "date_key": _day(i)})
        d = get_metric_correlation("heart_rate", "blood_sugar")
    assert d["has_data"] is False and "shared" in d["reason"]


def test_positive_correlation(app):
    _, uid = _uid(app, "corr2@medeasy.test")
    with user_context(uid):
        # sugar and heart rate rise together across 8 days
        for i in range(8):
            log_vital({"type": "blood_sugar", "value1": 90 + i * 5, "date_key": _day(i)})
            log_vital({"type": "heart_rate",  "value1": 60 + i * 3, "date_key": _day(i)})
        d = get_metric_correlation("blood_sugar", "heart_rate")
    assert d["has_data"] is True and d["n"] == 8
    assert d["r"] > 0.9 and d["direction"] == "together"


def test_inverse_correlation(app):
    _, uid = _uid(app, "corr3@medeasy.test")
    with user_context(uid):
        for i in range(8):
            log_sleep({"bedtime": f"{_day(i+1)}T23:00", "wake_time": f"{_day(i)}T{6+i:02d}:00"})  # sleep grows
            log_vital({"type": "heart_rate", "value1": 80 - i * 2, "date_key": _day(i)})           # HR falls
        d = get_metric_correlation("sleep_hours", "heart_rate")
    assert d["has_data"] is True and d["r"] < 0 and d["direction"] == "opposite"


def test_same_metric_rejected(app):
    _, uid = _uid(app, "corr4@medeasy.test")
    with user_context(uid):
        d = get_metric_correlation("weight", "weight")
    assert d["has_data"] is False


def test_options_and_api(app):
    c, uid = _uid(app, "corr5@medeasy.test")
    with user_context(uid):
        for i in range(4):
            log_vital({"type": "blood_pressure", "value1": 120 + i, "value2": 80, "date_key": _day(i)})
        opts = get_correlatable_metrics()
    assert any(m["key"] == "blood_pressure" for m in opts["metrics"])
    body = c.get("/api/metrics/options").get_json()
    assert "metrics" in body
