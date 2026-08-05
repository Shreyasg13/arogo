"""Doctor visit prep pack — what changed since the last doctor appointment."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.insights import get_visit_prep
from db.health import log_vital, create_appointment
from db.labs import log_lab_result

PW = "vp-pw-123456"


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


def _day(offset):
    return (dt.date.today() - dt.timedelta(days=offset)).isoformat()


def test_no_past_visit_is_empty(app):
    _, uid = _uid(app, "vp1@medeasy.test")
    with user_context(uid):
        # a FUTURE doctor appt doesn't anchor a "since last visit" view
        create_appointment({"title": "Checkup", "kind": "doctor", "date": _day(-10)})
        p = get_visit_prep()
    assert p["last_visit"] is None and p["has_data"] is False


def test_vitals_change_since_visit(app):
    _, uid = _uid(app, "vp2@medeasy.test")
    with user_context(uid):
        log_vital({"type": "blood_pressure", "value1": 150, "value2": 95, "date_key": _day(40)})
        create_appointment({"title": "GP", "kind": "doctor", "date": _day(30)})
        log_vital({"type": "blood_pressure", "value1": 128, "value2": 82, "date_key": _day(3)})
        p = get_visit_prep()
    assert p["last_visit"]["date"] == _day(30)
    bp = next(v for v in p["vitals_changes"] if v["type"] == "blood_pressure")
    assert bp["from"]["value1"] == 150 and bp["from"]["date"] == _day(40)   # baseline before visit
    assert bp["to"]["value1"] == 128 and bp["to"]["date"] == _day(3)        # latest since


def test_no_change_when_only_reading_predates_visit(app):
    _, uid = _uid(app, "vp3@medeasy.test")
    with user_context(uid):
        log_vital({"type": "heart_rate", "value1": 70, "date_key": _day(40)})
        create_appointment({"title": "GP", "kind": "doctor", "date": _day(30)})
        p = get_visit_prep()   # nothing logged AFTER the visit → no delta
    assert all(v["type"] != "heart_rate" for v in p["vitals_changes"])


def test_new_labs_since_visit(app):
    _, uid = _uid(app, "vp4@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "GP", "kind": "doctor", "date": _day(20)})
        log_lab_result("hba1c", 6.2, _day(5))
        log_lab_result("hba1c", 7.0, _day(40))   # older than visit → excluded (and not latest)
        p = get_visit_prep()
    keys = [l["date"] for l in p["new_labs"]]
    assert _day(5) in keys and _day(40) not in keys


def test_api_includes_visit_prep(app):
    c, uid = _uid(app, "vp5@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "GP", "kind": "doctor", "date": _day(15)})
        log_vital({"type": "weight", "value1": 80, "date_key": _day(20)})
        log_vital({"type": "weight", "value1": 78, "date_key": _day(2)})
    body = c.get("/api/doctor-summary").get_json()
    assert "visit_prep" in body
    assert body["visit_prep"]["last_visit"]["date"] == _day(15)
