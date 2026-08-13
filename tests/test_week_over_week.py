"""I10 — this week vs last delta card. Compares the last 7 days with the 7 before
across core metrics, and reports a metric ONLY when both weeks have data. From
the user's own logs."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.week_review import get_week_over_week

PW = "wow-pw-123456"


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


def _sleep(uid, day, hours):
    execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), day, day+"T23:00", day+"T07:00", hours, 3, day+"T07:00", uid), commit=True)


def _weight(uid, day, kg):
    execute("""INSERT INTO body_metrics (id,date_key,weight_kg,created_at,user_id)
               VALUES (?,?,?,?,?)""",
            (new_id(), day, kg, day+"T08:00", uid), commit=True)


def _this(n):   # n days into the current 7-day window (0..6)
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def _last(n):   # n days into the previous window (7..13)
    return (dt.date.today() - dt.timedelta(days=7 + n)).isoformat()


def _m(d, key):
    return next((x for x in d["metrics"] if x["key"] == key), None)


def test_empty_without_data(app):
    _, uid = _uid(app, "wow1@medeasy.test")
    with user_context(uid):
        d = get_week_over_week()
    assert d["has_data"] is False and d["metrics"] == []


def test_sleep_delta_both_weeks(app):
    _, uid = _uid(app, "wow2@medeasy.test")
    with user_context(uid):
        _sleep(uid, _this(1), 7.0); _sleep(uid, _this(3), 7.0)     # this week avg 7.0
        _sleep(uid, _last(1), 6.0); _sleep(uid, _last(3), 6.0)     # last week avg 6.0
        d = get_week_over_week()
    s = _m(d, "sleep")
    assert s and s["this"] == 7.0 and s["last"] == 6.0
    assert s["delta"] == 1.0 and s["dir"] == "up" and s["higher_better"] is True


def test_metric_needs_both_weeks(app):
    _, uid = _uid(app, "wow3@medeasy.test")
    with user_context(uid):
        _sleep(uid, _this(2), 8.0)      # only this week — no comparison possible
        d = get_week_over_week()
    assert _m(d, "sleep") is None       # dropped: last week is empty


def test_weight_direction_is_neutral(app):
    _, uid = _uid(app, "wow4@medeasy.test")
    with user_context(uid):
        _weight(uid, _this(1), 71.0)
        _weight(uid, _last(1), 70.0)
        d = get_week_over_week()
    w = _m(d, "weight")
    assert w and w["delta"] == 1.0 and w["dir"] == "up"
    assert w["higher_better"] is None    # weight up/down carries no built-in verdict


def test_api(app):
    c, uid = _uid(app, "wow5@medeasy.test")
    with user_context(uid):
        _sleep(uid, _this(1), 7.5); _sleep(uid, _last(1), 7.0)
    body = c.get("/api/week-over-week").get_json()
    assert body["has_data"] is True and any(m["key"] == "sleep" for m in body["metrics"])
