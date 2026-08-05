"""Health review recap — adherence %, vitals direction, goal progress, honest
wins, and a weekly/monthly window."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.insights import generate_health_review
from db.goals import create_goal

PW = "rev-pw-123456"


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


def _ago(n):
    return (_dt.date.today() - _dt.timedelta(days=n)).isoformat()


def _sleep(uid, dkey, h):
    execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,notes,created_at,user_id)
               VALUES (?,?,'23:00','07:00',?,4,'',?,?)""", (new_id(), dkey, h, now_iso(), uid), commit=True)


def _bp(uid, systolic, dia, ts):
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id)
               VALUES (?,?,'blood_pressure',?,?,'mmHg',?,?)""",
            (new_id(), ts[:10], systolic, dia, ts, uid), commit=True)


def test_period_label_toggle(app):
    _, uid = _uid(app, "rev1@medeasy.test")
    with user_context(uid):
        assert generate_health_review(7)["period"]["label"] == "Last 7 days"
        assert generate_health_review(30)["period"]["label"] == "Last 30 days"
        assert generate_health_review(30)["period"]["days"] == 30


def test_sleep_win_and_average(app):
    _, uid = _uid(app, "rev2@medeasy.test")
    with user_context(uid):
        for n in range(7):
            _sleep(uid, _ago(n), 8.0)
        rev = generate_health_review(7)
    assert rev["sleep"]["avg_hours"] == 8.0 and rev["sleep"]["nights"] == 7
    assert any("sleep" in w["text"].lower() for w in rev["wins"])


def test_vitals_direction_down(app):
    _, uid = _uid(app, "rev3@medeasy.test")
    with user_context(uid):
        base = _dt.datetime.now()
        for i, sys in enumerate([140, 138, 130, 124]):     # falling BP
            ts = (base - _dt.timedelta(days=4 - i)).isoformat()
            _bp(uid, sys, 85, ts)
        rev = generate_health_review(30)
    bp = next(v for v in rev["vitals"] if v["type"] == "blood_pressure")
    assert bp["direction"] == "down" and bp["latest"] == "124/85" and bp["readings"] == 4


def test_vitals_direction_none_when_too_few(app):
    _, uid = _uid(app, "rev4@medeasy.test")
    with user_context(uid):
        base = _dt.datetime.now()
        _bp(uid, 130, 80, (base - _dt.timedelta(days=2)).isoformat())
        _bp(uid, 128, 80, (base - _dt.timedelta(days=1)).isoformat())
        rev = generate_health_review(30)
    bp = next(v for v in rev["vitals"] if v["type"] == "blood_pressure")
    assert bp["direction"] is None and bp["latest"] == "128/80"


def test_goal_progress_in_review(app):
    _, uid = _uid(app, "rev5@medeasy.test")
    with user_context(uid):
        create_goal("steps", 8000, "reach")
        rev = generate_health_review(7)
    titles = [g["metric_name"] for g in rev["goals"]]
    assert "Daily steps" in titles


def test_no_adherence_without_meds(app):
    _, uid = _uid(app, "rev6@medeasy.test")
    with user_context(uid):
        rev = generate_health_review(7)
    assert rev["adherence"] is None      # honest: nothing scheduled to adhere to


def test_api_endpoint(app):
    c, uid = _uid(app, "rev7@medeasy.test")
    r = c.get("/api/report/review?days=30")
    assert r.status_code == 200
    body = r.get_json()
    assert body["period"]["days"] == 30 and "wins" in body and "vitals" in body
