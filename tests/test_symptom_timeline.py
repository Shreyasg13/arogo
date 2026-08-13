"""Symptom ↔ medicine timeline: coincidence in time (never a causal claim)."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "tl-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "symtl1@medeasy.test", "password": PW})
    return c


def test_timeline_separates_new_meds_from_ongoing_and_sorts(client):
    old = (dt.date.today() - dt.timedelta(days=200)).isoformat()   # before 90d window
    recent = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    client.post("/api/medicines", json={
        "name": "OldStatin", "frequency": "once_daily", "times": ["09:00"], "start_date": old})
    client.post("/api/medicines", json={
        "name": "NewPill", "frequency": "once_daily", "times": ["09:00"], "start_date": recent})
    client.post("/api/symptoms", json={"name": "Nausea", "severity": 6})

    tl = client.get("/api/symptoms/timeline?days=90").get_json()
    assert tl["has_data"] is True
    started = {m["name"]: m for m in tl["meds"]}
    assert started["NewPill"]["started_in_window"] is True
    assert started["OldStatin"]["started_in_window"] is False
    # meds sorted by start_date ascending → the 200-day-old one comes first
    assert [m["name"] for m in tl["meds"]] == ["OldStatin", "NewPill"]
    assert tl["symptoms"][0]["name"] == "Nausea"
    assert tl["range"]["days"] == 90


def test_timeline_has_data_false_when_no_symptoms(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "symtl2@medeasy.test", "password": PW})
    c.post("/api/medicines", json={"name": "Solo", "frequency": "once_daily", "times": ["09:00"]})
    tl = c.get("/api/symptoms/timeline").get_json()
    assert tl["has_data"] is False and tl["symptoms"] == []


def test_timeline_clamps_days_and_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/symptoms/timeline").status_code == 401
    c.post("/auth/register", json={"email": "symtl3@medeasy.test", "password": PW})
    # out-of-range days are clamped into [7, 365]
    assert c.get("/api/symptoms/timeline?days=9000").get_json()["range"]["days"] == 365
    assert c.get("/api/symptoms/timeline?days=1").get_json()["range"]["days"] == 7
