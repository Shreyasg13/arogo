"""Weight progress: measured pace + ETA from actual weigh-ins."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "wgt-pw-123456"


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


def _ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def _logw(c, kg, date):
    c.post("/api/body-metrics", json={"weight_kg": kg, "date_key": date})


def test_measured_pace_comes_from_real_weighins_not_the_goal(app):
    c = _register(app, "wgt1@medeasy.test")
    c.post("/api/food/profile", json={"target_weight_kg": 76.0, "goal": "lose"})
    # Lost 2 kg over 28 days → measured pace ≈ -0.5 kg/week.
    _logw(c, 82.0, _ago(28))
    _logw(c, 80.0, _ago(0))
    s = c.get("/api/body-metrics/trend?days=90").get_json()["stats"]
    assert s["measured_rate_per_week"] == -0.5
    # goal-assumed rate for 'lose' is -0.25 — the measured one is different & real
    assert s["measured_rate_per_week"] != s["rate_per_week"]
    assert s["on_track"] is True
    assert s["measured_eta_date"] is not None      # heading toward 76 kg


def test_moving_away_from_goal_gives_no_eta_and_flags_off_track(app):
    c = _register(app, "wgt2@medeasy.test")
    c.post("/api/food/profile", json={"target_weight_kg": 70.0, "goal": "lose"})
    # Gaining while the goal is to lose → not on track, no honest ETA.
    _logw(c, 80.0, _ago(21))
    _logw(c, 82.0, _ago(0))
    s = c.get("/api/body-metrics/trend?days=90").get_json()["stats"]
    assert s["measured_rate_per_week"] > 0
    assert s["on_track"] is False and s["measured_eta_date"] is None


def test_too_short_a_span_yields_no_measured_pace(app):
    c = _register(app, "wgt3@medeasy.test")
    c.post("/api/food/profile", json={"target_weight_kg": 70.0, "goal": "lose"})
    _logw(c, 80.0, _ago(3))
    _logw(c, 79.5, _ago(0))       # only 3 days apart — below the 7-day minimum
    s = c.get("/api/body-metrics/trend?days=90").get_json()["stats"]
    assert s["measured_rate_per_week"] is None
