"""N-of-1 self-experiments — honest before/after over the user's own logs."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db.experiments import (create_experiment, list_experiments, get_experiment,
                            end_experiment, delete_experiment, metric_options, MIN_READINGS)

PW = "exp-pw-12345"


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
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=n)).isoformat()


def _sleep(uid, date_key, h):
    execute("INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,created_at,user_id) "
            "VALUES (?,?,?,?,?,?,?)", (new_id(), date_key, "23:00", "07:00", h, now_iso(), uid), commit=True)


def test_metric_options_present():
    keys = {m["key"] for m in metric_options()}
    assert {"sleep_hours", "bp_systolic", "weight", "symptom_freq"} <= keys


def test_validation(app):
    _, uid = _uid(app, "nof11@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_experiment({"title": "", "metric": "sleep_hours"})
        with pytest.raises(ValueError):
            create_experiment({"title": "x", "metric": "not_a_metric"})


def test_before_after_and_delta(app):
    _, uid = _uid(app, "nof12@medeasy.test")
    with user_context(uid):
        # baseline (10 days ago .. before start): ~6h; after (since start=5 days ago): ~7.5h
        for d in (8, 7, 6):        # before window (start=5 → baseline covers days 6..19)
            _sleep(uid, _ago(d), 6.0)
        for d in (4, 3, 2, 1):     # after window (start .. today)
            _sleep(uid, _ago(d), 7.5)
        exp = create_experiment({"title": "No screens after 10pm", "metric": "sleep_hours",
                                 "start_date": _ago(5), "baseline_days": 14})
        r = exp["result"]
    assert r["enough_data"] is True
    assert r["before"]["avg"] == 6.0 and r["after"]["avg"] == 7.5
    assert r["delta"] == 1.5
    assert r["metric_label"] == "Sleep" and r["unit"] == "h"


def test_not_enough_data_is_honest(app):
    _, uid = _uid(app, "nof13@medeasy.test")
    with user_context(uid):
        _sleep(uid, _ago(2), 7.0)   # only 1 reading after, none before
        exp = create_experiment({"title": "try", "metric": "sleep_hours", "start_date": _ago(5)})
        r = exp["result"]
    assert r["enough_data"] is False
    assert r["delta"] is None                       # never invents a comparison
    assert r["min_readings"] == MIN_READINGS


def test_end_and_freeze_window(app):
    _, uid = _uid(app, "nof14@medeasy.test")
    with user_context(uid):
        exp = create_experiment({"title": "t", "metric": "weight", "start_date": _ago(10)})
        ended = end_experiment(exp["id"])
    assert ended["status"] == "ended" and ended["end_date"] == user_today()


def test_isolation_and_delete(app):
    _, a = _uid(app, "nof15a@medeasy.test")
    _, b = _uid(app, "nof15b@medeasy.test")
    with user_context(a):
        exp = create_experiment({"title": "mine", "metric": "weight", "start_date": _ago(3)})
    with user_context(b):
        assert get_experiment(exp["id"]) is None      # B can't see A's experiment
        assert list_experiments() == []
    with user_context(a):
        delete_experiment(exp["id"])
        assert get_experiment(exp["id"]) is None


def test_routes(app):
    c, _ = _uid(app, "nof16@medeasy.test")
    assert c.get("/api/experiments").status_code == 200
    r = c.post("/api/experiments", json={"title": "coffee", "metric": "heart_rate"}).get_json()
    assert r["success"]
    eid = r["experiment"]["id"]
    assert c.post(f"/api/experiments/{eid}/end").get_json()["success"]
    assert c.delete(f"/api/experiments/{eid}").get_json()["success"]


def test_route_requires_auth(app):
    assert app.test_client().get("/api/experiments").status_code in (401, 403)
