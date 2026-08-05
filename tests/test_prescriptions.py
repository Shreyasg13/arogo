"""Prescription library — link to medicines, renewal status from valid_until,
per-user isolation."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.prescriptions import (create_prescription, update_prescription,
                              delete_prescription, list_prescriptions)

PW = "rx-pw-123456"


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


def _ahead(n):
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def _med(c, name):
    return c.post("/api/medicines", json={"name": name, "frequency": "once_daily",
                                          "times": ["09:00"]}).get_json()["medicine"]["id"]


def test_create_links_owned_medicines(app):
    c, uid = _uid(app, "rx1@medeasy.test")
    m1, m2 = _med(c, "Metformin"), _med(c, "Losartan")
    with user_context(uid):
        p = create_prescription({"prescriber": "Dr Nair", "medicine_ids": [m1, m2, "not-mine"]})
    names = sorted(m["name"] for m in p["medicines"])
    assert names == ["Losartan", "Metformin"]      # foreign id dropped
    assert p["medicine_ids"] == [m1, m2]


def test_requires_prescriber_or_medicine(app):
    _, uid = _uid(app, "rx2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_prescription({"notes": "nothing useful"})


def test_expiry_status(app):
    _, uid = _uid(app, "rx3@medeasy.test")
    with user_context(uid):
        expired = create_prescription({"prescriber": "A", "valid_until": _ago(3)})
        expiring = create_prescription({"prescriber": "B", "valid_until": _ahead(5)})
        valid = create_prescription({"prescriber": "C", "valid_until": _ahead(90)})
        none = create_prescription({"prescriber": "D"})
    assert expired["status"] == "expired" and expired["days_until_expiry"] == -3
    assert expiring["status"] == "expiring" and expiring["days_until_expiry"] == 5
    assert valid["status"] == "valid"
    assert none["status"] is None


def test_refills_clamped(app):
    _, uid = _uid(app, "rx4@medeasy.test")
    with user_context(uid):
        p = create_prescription({"prescriber": "A", "refills_left": 999})
        assert p["refills_left"] == 99
        p2 = create_prescription({"prescriber": "B", "refills_left": -5})
        assert p2["refills_left"] == 0


def test_attention_count(app):
    _, uid = _uid(app, "rx5@medeasy.test")
    with user_context(uid):
        create_prescription({"prescriber": "A", "valid_until": _ago(1)})     # expired
        create_prescription({"prescriber": "B", "refills_left": 0})           # no refills
        create_prescription({"prescriber": "C", "valid_until": _ahead(200)})  # fine
        out = list_prescriptions()
    assert out["attention_count"] == 2


def test_update_and_delete(app):
    _, uid = _uid(app, "rx6@medeasy.test")
    with user_context(uid):
        p = create_prescription({"prescriber": "Dr X"})
        upd = update_prescription(p["id"], {"refills_left": 2, "valid_until": _ahead(30)})
        assert upd["refills_left"] == 2 and upd["status"] == "valid"
        delete_prescription(p["id"])
        assert list_prescriptions()["prescriptions"] == []


def test_update_reenforces_prescriber_or_medicine(app):
    _, uid = _uid(app, "rx10@medeasy.test")
    with user_context(uid):
        p = create_prescription({"prescriber": "Dr X"})
        with pytest.raises(ValueError):           # can't empty it out via update
            update_prescription(p["id"], {"prescriber": "", "medicine_ids": []})


def test_isolation(app):
    c_a, uid_a = _uid(app, "rx7@medeasy.test")
    _, uid_b = _uid(app, "rx8@medeasy.test")
    with user_context(uid_a):
        create_prescription({"prescriber": "SecretDoc"})
    with user_context(uid_b):
        assert list_prescriptions()["prescriptions"] == []


def test_api_round_trip(app):
    c, uid = _uid(app, "rx9@medeasy.test")
    r = c.post("/api/prescriptions", json={"prescriber": "Dr API", "refills_left": 3})
    assert r.status_code == 200
    pid = r.get_json()["prescription"]["id"]
    assert c.get("/api/prescriptions").get_json()["prescriptions"][0]["prescriber"] == "Dr API"
    assert c.patch(f"/api/prescriptions/{pid}", json={"refills_left": 0}).get_json()["prescription"]["refills_left"] == 0
    assert c.delete(f"/api/prescriptions/{pid}").get_json()["success"] is True
    assert c.post("/api/prescriptions", json={"notes": "empty"}).status_code == 400
