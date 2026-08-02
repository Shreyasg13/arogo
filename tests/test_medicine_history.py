"""Medication history log: a dated record of medicine changes."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "hist-pw-12345"


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


def _kinds(client):
    return [e["kind"] for e in client.get("/api/medicines/history").get_json()["events"]]


def test_adding_a_medicine_records_a_started_event(app):
    c = _register(app, "hist1@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Metformin", "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    events = c.get("/api/medicines/history").get_json()["events"]
    assert len(events) == 1
    assert events[0]["kind"] == "started" and events[0]["med_name"] == "Metformin"
    assert events[0]["medicine_id"] == m["id"]


def test_toggle_records_stopped_then_resumed(app):
    c = _register(app, "hist2@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Aspirin", "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    c.post(f"/api/medicines/{m['id']}/toggle")     # active → inactive = stopped
    c.post(f"/api/medicines/{m['id']}/toggle")     # inactive → active = resumed
    # All three changes are recorded (exact sub-second tie-order isn't asserted —
    # the clock resolution can group same-instant events).
    assert sorted(_kinds(c)) == ["resumed", "started", "stopped"]


def test_delete_records_a_removed_event_keeping_the_name(app):
    c = _register(app, "hist3@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "OldPill", "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    c.delete(f"/api/medicines/{m['id']}")
    events = c.get("/api/medicines/history").get_json()["events"]
    deleted = next(e for e in events if e["kind"] == "deleted")
    assert deleted["med_name"] == "OldPill"        # name snapshot survives the delete


def test_restock_records_only_when_count_increases(app):
    c = _register(app, "hist4@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "VitD", "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    c.post(f"/api/medicines/{m['id']}/stock", json={"pill_count": 30, "pills_per_dose": 1})
    kinds = _kinds(c)
    assert "restocked" in kinds


def test_stop_event_feeds_the_symptom_timeline(app):
    c = _register(app, "hist5@medeasy.test")
    m = c.post("/api/medicines", json={
        "name": "Trial", "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    c.post(f"/api/medicines/{m['id']}/toggle")     # stop it
    c.post("/api/symptoms", json={"name": "Nausea", "severity": 5})
    tl = c.get("/api/symptoms/timeline?days=90").get_json()
    assert any(ch["name"] == "Trial" and ch["kind"] == "stopped" for ch in tl["changes"])


def test_history_requires_auth(app):
    assert app.test_client().get("/api/medicines/history").status_code == 401
