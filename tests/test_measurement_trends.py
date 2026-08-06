"""Body-measurement trends — girth change over time + a recomposition read."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.wellness import log_body_metric, get_measurement_trends

PW = "meas-pw-12345"


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


def _log(day_offset, **fields):
    fields["date_key"] = (dt.date.today() - dt.timedelta(days=day_offset)).isoformat()
    log_body_metric(fields)


def _t(trends, field):
    return next((x for x in trends if x["field"] == field), None)


def test_waist_change(app):
    _, uid = _uid(app, "meas1@medeasy.test")
    with user_context(uid):
        _log(60, waist_cm=90)
        _log(1, waist_cm=85)
        d = get_measurement_trends()
    w = _t(d["trends"], "waist_cm")
    assert w["first"] == 90 and w["latest"] == 85 and w["change"] == -5.0
    assert w["unit"] == "cm" and w["points"] == 2


def test_single_point_not_trended(app):
    _, uid = _uid(app, "meas2@medeasy.test")
    with user_context(uid):
        _log(1, chest_cm=100)
        d = get_measurement_trends()
    assert _t(d["trends"], "chest_cm") is None    # needs >=2 points


def test_recomp_read(app):
    _, uid = _uid(app, "meas3@medeasy.test")
    with user_context(uid):
        _log(60, weight_kg=75, waist_cm=88)
        _log(1, weight_kg=75.5, waist_cm=84)       # weight held, waist down 4cm
        d = get_measurement_trends()
    assert d["recomp"] and d["recomp"]["kind"] == "recomp"
    assert d["recomp"]["waist_change"] == -4.0


def test_fat_loss_read(app):
    _, uid = _uid(app, "meas4@medeasy.test")
    with user_context(uid):
        _log(60, weight_kg=80, waist_cm=95)
        _log(1, weight_kg=76, waist_cm=90)         # weight down AND waist down
        d = get_measurement_trends()
    assert d["recomp"] and d["recomp"]["kind"] == "fat_loss"


def test_no_recomp_without_both_series(app):
    _, uid = _uid(app, "meas5@medeasy.test")
    with user_context(uid):
        _log(30, waist_cm=88)
        _log(1, waist_cm=85)                        # waist only, no weight series
        d = get_measurement_trends()
    assert d["recomp"] is None


def test_api(app):
    c, uid = _uid(app, "meas6@medeasy.test")
    with user_context(uid):
        _log(30, hip_cm=100); _log(1, hip_cm=97)
    body = c.get("/api/body-metrics/measurements").get_json()
    assert body["has_data"] is True
    assert _t(body["trends"], "hip_cm")["change"] == -3.0
