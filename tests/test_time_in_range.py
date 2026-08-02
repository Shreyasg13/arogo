"""Time-in-range for vitals: % of readings within the reference band."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "tir-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _bp(c, sys, dia):
    c.post("/api/vitals", json={"type": "blood_pressure", "value1": sys, "value2": dia, "unit": "mmHg"})


def _sugar(c, v):
    c.post("/api/vitals", json={"type": "blood_sugar", "value1": v, "unit": "mg/dL"})


def test_bp_time_in_range_splits_low_in_high(app):
    c = _register(app, "tir1@medeasy.test")
    _bp(c, 118, 78)   # in
    _bp(c, 115, 75)   # in
    _bp(c, 150, 95)   # high
    _bp(c, 85, 55)    # low
    tir = c.get("/api/vitals/trend?days=30").get_json()["tir"]["blood_pressure"]
    assert tir["total"] == 4
    assert tir["in"] == 2 and tir["high"] == 1 and tir["low"] == 1
    assert tir["pct"] == 50
    assert "90–120" in tir["band"]


def test_blood_sugar_in_range_percentage(app):
    c = _register(app, "tir2@medeasy.test")
    for v in (90, 95, 88):    # in (70–99)
        _sugar(c, v)
    _sugar(c, 140)            # high
    tir = c.get("/api/vitals/trend?days=30").get_json()["tir"]["blood_sugar"]
    assert tir["in"] == 3 and tir["high"] == 1 and tir["pct"] == 75


def test_fewer_than_three_readings_has_no_tir(app):
    c = _register(app, "tir3@medeasy.test")
    _sugar(c, 90)
    _sugar(c, 95)             # only 2 readings
    tir = c.get("/api/vitals/trend?days=30").get_json()["tir"]
    assert "blood_sugar" not in tir


def test_spo2_only_has_a_floor(app):
    c = _register(app, "tir4@medeasy.test")
    for v in (97, 98, 96):    # in (≥95)
        c.post("/api/vitals", json={"type": "spo2", "value1": v, "unit": "%"})
    c.post("/api/vitals", json={"type": "spo2", "value1": 90, "unit": "%"})   # low
    tir = c.get("/api/vitals/trend?days=30").get_json()["tir"]["spo2"]
    assert tir["in"] == 3 and tir["low"] == 1 and tir["high"] == 0
