"""Adherence goal + month-end forecast (projects at your current rate)."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import (get_adherence_goal, set_adherence_goal, get_adherence_forecast,
                          insert_medicine, log_dose)

PW = "afc-pw-12345"


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


def test_goal_set_get_clear(app):
    _, uid = _uid(app, "afc1@medeasy.test")
    with user_context(uid):
        assert get_adherence_goal() is None
        assert set_adherence_goal(90) == 90
        assert set_adherence_goal(150) == 100      # clamped
        assert set_adherence_goal(0) is None       # cleared
        assert get_adherence_goal() is None


def test_forecast_projects_current_rate(app):
    _, uid = _uid(app, "afc2@medeasy.test")
    # med started at the 1st of THIS month so every day this month is scheduled
    first = dt.date.today().replace(day=1).isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Metformin", "frequency": "once_daily",
                               "times": ["09:00"], "start_date": first})["id"]
        # take today's dose only; earlier days this month left as missed
        log_dose(mid, dt.date.today().isoformat(), "09:00", taken=True)
        f = get_adherence_forecast()
    assert f["has_data"] is True
    # current rate = taken_to_date / scheduled_to_date; projected equals it
    assert f["projected_pct"] == f["current_pct"]
    assert f["taken_to_date"] == 1


def test_goal_relative_fields(app):
    _, uid = _uid(app, "afc3@medeasy.test")
    first = dt.date.today().replace(day=1).isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "BP med", "frequency": "once_daily",
                               "times": ["08:00"], "start_date": first})["id"]
        log_dose(mid, dt.date.today().isoformat(), "08:00", taken=True)
        set_adherence_goal(80)
        f = get_adherence_forecast()
    assert f["goal_pct"] == 80
    assert f["on_track"] in (True, False)
    assert f["misses_allowed"] is not None and f["misses_allowed"] >= 0


def test_no_goal_leaves_goal_fields_none(app):
    _, uid = _uid(app, "afc4@medeasy.test")
    first = dt.date.today().replace(day=1).isoformat()
    with user_context(uid):
        insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"], "start_date": first})
        f = get_adherence_forecast()
    assert f["goal_pct"] is None and f["on_track"] is None and f["misses_allowed"] is None


def test_api(app):
    c, uid = _uid(app, "afc5@medeasy.test")
    assert c.post("/api/medicines/adherence/goal", json={"pct": 85}).get_json()["goal_pct"] == 85
    assert c.get("/api/medicines/adherence/goal").get_json()["goal_pct"] == 85
    body = c.get("/api/medicines/adherence/forecast").get_json()
    assert "projected_pct" in body and "month" in body
