"""Lab recheck reminders — interval-based 'due' derived from the user's own
latest result date; honest 'no baseline' when nothing's been logged."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.labs import (log_lab_result, set_lab_recheck, clear_lab_recheck,
                     get_lab_rechecks, suggested_recheck_days)

PW = "labr-pw-12345"


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


def _find(res, key):
    return next((r for r in res["rechecks"] if r["lab_key"] == key), None)


def test_due_when_interval_elapsed(app):
    _, uid = _uid(app, "labr1@medeasy.test")
    with user_context(uid):
        log_lab_result("hba1c", 6.4, _ago(100))     # done 100 days ago
        set_lab_recheck("hba1c", 90)                 # due every 90 → overdue
        res = get_lab_rechecks()
    r = _find(res, "hba1c")
    assert r["status"] == "due" and r["days_until"] == -10
    assert res["due_count"] == 1


def test_ok_when_recent(app):
    _, uid = _uid(app, "labr2@medeasy.test")
    with user_context(uid):
        log_lab_result("ldl", 110, _ago(10))
        set_lab_recheck("ldl", 180)
        res = get_lab_rechecks()
    assert _find(res, "ldl")["status"] == "ok"


def test_soon_within_two_weeks(app):
    _, uid = _uid(app, "labr3@medeasy.test")
    with user_context(uid):
        log_lab_result("tsh", 2.0, _ago(175))
        set_lab_recheck("tsh", 180)                  # due in 5 days
        res = get_lab_rechecks()
    r = _find(res, "tsh")
    assert r["status"] == "soon" and r["days_until"] == 5


def test_no_baseline_when_never_logged(app):
    _, uid = _uid(app, "labr4@medeasy.test")
    with user_context(uid):
        set_lab_recheck("vitamin_d", 180)            # no result logged
        res = get_lab_rechecks()
    r = _find(res, "vitamin_d")
    assert r["status"] == "no_baseline" and r["next_due"] is None


def test_set_is_idempotent_and_clamped(app):
    _, uid = _uid(app, "labr5@medeasy.test")
    with user_context(uid):
        set_lab_recheck("ldl", 90)
        set_lab_recheck("ldl", 120)                  # replaces, not duplicates
        set_lab_recheck("hdl", 99999)                # clamped to <= 3650
        res = get_lab_rechecks()
        rows = execute("SELECT interval_days FROM lab_rechecks WHERE user_id=? AND lab_key='ldl'",
                       (uid,), fetchall=True)
    assert len(rows) == 1 and rows[0]["interval_days"] == 120
    assert _find(res, "hdl")["interval_days"] == 3650


def test_clear(app):
    _, uid = _uid(app, "labr6@medeasy.test")
    with user_context(uid):
        set_lab_recheck("hba1c", 90)
        clear_lab_recheck("hba1c")
        res = get_lab_rechecks()
    assert res["rechecks"] == []


def test_suggested_intervals(app):
    assert suggested_recheck_days("hba1c") == 90
    assert suggested_recheck_days("unknown_test") == 180


def test_isolation(app):
    _, uid_a = _uid(app, "labr7@medeasy.test")
    _, uid_b = _uid(app, "labr8@medeasy.test")
    with user_context(uid_a):
        set_lab_recheck("hba1c", 90)
    with user_context(uid_b):
        assert get_lab_rechecks()["rechecks"] == []


def test_api_round_trip(app):
    c, uid = _uid(app, "labr9@medeasy.test")
    c.post("/api/labs", json={"lab_key": "hba1c", "value": 6.0, "date_key": _ago(200)})
    assert c.post("/api/labs/rechecks", json={"lab_key": "hba1c"}).status_code == 200   # uses suggested 90
    body = c.get("/api/labs/rechecks").get_json()
    assert body["rechecks"][0]["status"] == "due"
    assert c.delete("/api/labs/rechecks/hba1c").get_json()["success"] is True
    assert c.get("/api/labs/rechecks").get_json()["rechecks"] == []
