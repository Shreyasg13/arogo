"""Immunization tracker — dose records + honest next-due estimates for the
recurring vaccines (tetanus, flu, typhoid)."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.immunizations import log_dose, get_record, delete_dose

PW = "vax-pw-12345"


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


def _ago(days):
    return (dt.date.today() - dt.timedelta(days=days)).isoformat()


def test_log_and_group(app):
    c, uid = _uid(app, "vax1@medeasy.test")
    with user_context(uid):
        log_dose("penta", _ago(400), "Dose 1")
        log_dose("penta", _ago(370), "Dose 2")
        rec = get_record()
    penta = next(v for v in rec["vaccines"] if v["key"] == "penta")
    assert penta["dose_count"] == 2 and rec["total_doses"] == 2
    assert penta["doses"][0]["date_given"] == _ago(370)   # newest first


def test_recurring_flu_next_due(app):
    c, uid = _uid(app, "vax2@medeasy.test")
    with user_context(uid):
        log_dose("influenza", _ago(400))       # over a year ago → overdue
        rec = get_record()
    flu = next(v for v in rec["vaccines"] if v["key"] == "influenza")
    assert flu["next_due"] is not None and flu["next_due"]["overdue"] is True
    assert any(d["key"] == "influenza" for d in rec["due"])


def test_flu_within_a_year_not_overdue(app):
    c, uid = _uid(app, "vax3@medeasy.test")
    with user_context(uid):
        log_dose("influenza", _ago(30))
        rec = get_record()
    flu = next(v for v in rec["vaccines"] if v["key"] == "influenza")
    assert flu["next_due"]["overdue"] is False


def test_one_time_vaccine_has_no_due(app):
    c, uid = _uid(app, "vax4@medeasy.test")
    with user_context(uid):
        log_dose("bcg", _ago(1000))
        rec = get_record()
    bcg = next(v for v in rec["vaccines"] if v["key"] == "bcg")
    assert bcg["next_due"] is None
    assert not any(d["key"] == "bcg" for d in rec["due"])


def test_rejects_bad_input(app):
    _, uid = _uid(app, "vax5@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            log_dose("influenza", "not-a-date")
        with pytest.raises(ValueError):
            log_dose("", _ago(10))


def test_api_round_trip(app):
    c, uid = _uid(app, "vax6@medeasy.test")
    r = c.post("/api/immunizations", json={"vaccine_key": "td", "date_given": _ago(20), "dose_label": "Booster"})
    assert r.status_code == 200
    rec = c.get("/api/immunizations").get_json()
    assert rec["total_doses"] == 1
    assert c.get("/api/immunizations/catalog").get_json()["categories"]
    assert c.post("/api/immunizations", json={"vaccine_key": "td", "date_given": "bad"}).status_code == 400
    # non-string vaccine_key is a clean 400, not a 500
    assert c.post("/api/immunizations", json={"vaccine_key": [1], "date_given": _ago(1)}).status_code == 400
