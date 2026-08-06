"""Vitals anomaly flags — out-of-band runs and monotonic trends, worth a glance."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.insights import get_vitals_anomalies
from db.health import log_vital
from db.vital_targets import set_target

PW = "anom-pw-12345"


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


def _bs(value, days_ago):
    log_vital({"type": "blood_sugar", "value1": value,
               "date_key": (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()})


def test_out_of_band_run_flagged(app):
    _, uid = _uid(app, "anom1@medeasy.test")
    with user_context(uid):
        set_target("blood_sugar", 80, 110)
        for i, v in enumerate([150, 145, 140]):     # last 3 all above target (newest first: 140 today)
            _bs(v, i)
        a = get_vitals_anomalies()
    f = next((x for x in a["flags"] if x["type"] == "blood_sugar"), None)
    assert f and f["kind"] == "out_of_band" and f["direction"] == "above" and f["run"] >= 3


def test_no_flag_without_enough_readings(app):
    _, uid = _uid(app, "anom2@medeasy.test")
    with user_context(uid):
        set_target("blood_sugar", 80, 110)
        _bs(150, 0); _bs(145, 1)                     # only 2 readings
        a = get_vitals_anomalies()
    assert not any(x["type"] == "blood_sugar" for x in a["flags"])


def test_monotonic_trend_flagged_without_target(app):
    _, uid = _uid(app, "anom3@medeasy.test")
    with user_context(uid):
        # rising heart rate over 5 readings, net well over the epsilon (5 bpm)
        for i, v in enumerate([80, 76, 72, 68, 64]):   # newest-first 80 today, oldest 64
            log_vital({"type": "heart_rate", "value1": v,
                       "date_key": (dt.date.today() - dt.timedelta(days=i)).isoformat()})
        a = get_vitals_anomalies()
    f = next((x for x in a["flags"] if x["type"] == "heart_rate"), None)
    assert f and f["kind"] == "trend" and f["direction"] == "up" and f["run"] >= 4


def test_tiny_wiggle_is_not_a_trend(app):
    _, uid = _uid(app, "anom4@medeasy.test")
    with user_context(uid):
        # monotonic but net change (0.4) below the weight epsilon (1.5)
        for i, v in enumerate([70.4, 70.3, 70.2, 70.1, 70.0]):
            execute("""INSERT INTO vitals (id,date_key,type,value1,logged_at,user_id)
                       VALUES (?,?,?,?,?,?)""",
                    (f"w{i}", (dt.date.today() - dt.timedelta(days=i)).isoformat(),
                     'weight', v, f"2026-08-0{i+1}T08:00:00", uid), commit=True)
        a = get_vitals_anomalies()
    assert not any(x["type"] == "weight" for x in a["flags"])


def test_isolation_and_api(app):
    c, uid_a = _uid(app, "anom5@medeasy.test")
    _, uid_b = _uid(app, "anom6@medeasy.test")
    with user_context(uid_a):
        set_target("blood_sugar", 80, 110)
        for i, v in enumerate([160, 155, 150]):
            _bs(v, i)
    body = c.get("/api/vitals/anomalies").get_json()
    assert body["has_data"] is True
    with user_context(uid_b):
        assert get_vitals_anomalies()["has_data"] is False   # B sees nothing of A's
