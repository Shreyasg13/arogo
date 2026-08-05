"""Medication tapering schedules — dated dose steps, current-step resolution."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.tapers import add_step, delete_step, get_taper, list_tapers

PW = "taper-pw-1234"


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


def _med(c, name="Prednisone"):
    return c.post("/api/medicines", json={"name": name, "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]["id"]


def _ago(n):
    return (_dt.date.today() - _dt.timedelta(days=n)).isoformat()


def _ahead(n):
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def test_current_step_resolution(app):
    c, uid = _uid(app, "taper1@medeasy.test")
    mid = _med(c)
    with user_context(uid):
        add_step({"medicine_id": mid, "dosage": "40mg", "start_date": _ago(10)})
        add_step({"medicine_id": mid, "dosage": "20mg", "start_date": _ago(3)})   # current
        add_step({"medicine_id": mid, "dosage": "10mg", "start_date": _ahead(4)})  # upcoming
        t = get_taper(mid)
    assert t["current"]["dosage"] == "20mg"
    assert t["next"]["dosage"] == "10mg" and t["next"]["days_until"] == 4
    statuses = [s["status"] for s in t["steps"]]
    assert statuses == ["past", "current", "upcoming"]


def test_all_future_no_current(app):
    c, uid = _uid(app, "taper2@medeasy.test")
    mid = _med(c)
    with user_context(uid):
        add_step({"medicine_id": mid, "dosage": "30mg", "start_date": _ahead(2)})
        t = get_taper(mid)
    assert t["current"] is None and t["next"]["dosage"] == "30mg"


def test_validation(app):
    c, uid = _uid(app, "taper3@medeasy.test")
    mid = _med(c)
    with user_context(uid):
        with pytest.raises(ValueError):
            add_step({"medicine_id": mid, "start_date": _ago(1)})          # no dose
        with pytest.raises(ValueError):
            add_step({"medicine_id": mid, "dosage": "5mg", "start_date": "nope"})
        with pytest.raises(ValueError):
            add_step({"medicine_id": "not-mine", "dosage": "5mg", "start_date": _ago(1)})


def test_overview_and_delete(app):
    c, uid = _uid(app, "taper4@medeasy.test")
    mid = _med(c, "Steroid")
    with user_context(uid):
        s = add_step({"medicine_id": mid, "dosage": "8mg", "start_date": _ago(1)})
        ov = list_tapers()
        assert len(ov) == 1 and ov[0]["name"] == "Steroid" and ov[0]["current"]["dosage"] == "8mg"
        delete_step(s["id"])
        assert list_tapers() == []


def test_isolation(app):
    c_a, uid_a = _uid(app, "taper5@medeasy.test")
    _, uid_b = _uid(app, "taper6@medeasy.test")
    mid = _med(c_a)
    with user_context(uid_a):
        add_step({"medicine_id": mid, "dosage": "10mg", "start_date": _ago(1)})
    with user_context(uid_b):
        assert list_tapers() == []
        assert get_taper(mid)["steps"] == []       # can't read another user's taper


def test_api_round_trip(app):
    c, uid = _uid(app, "taper7@medeasy.test")
    mid = _med(c)
    r = c.post("/api/tapers", json={"medicine_id": mid, "dosage": "40mg", "start_date": _ago(2)})
    assert r.status_code == 200
    sid = r.get_json()["step"]["id"]
    assert c.get(f"/api/tapers/{mid}").get_json()["current"]["dosage"] == "40mg"
    assert c.get("/api/tapers").get_json()["tapers"][0]["medicine_id"] == mid
    assert c.delete(f"/api/tapers/step/{sid}").get_json()["success"] is True
    assert c.post("/api/tapers", json={"medicine_id": mid}).status_code == 400
