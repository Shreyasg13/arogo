"""Printable medication card: schedule grouped by time + emergency contacts."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "card-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "card@medeasy.test", "password": PW})
    return c


def test_card_groups_scheduled_meds_by_time_and_labels_slots(client):
    client.post("/api/medicines", json={
        "name": "Metformin", "dosage": "500", "unit": "mg", "purpose": "diabetes",
        "frequency": "twice_daily", "times": ["09:00", "21:00"], "with_food": True})
    client.post("/api/medicines", json={
        "name": "Aspirin", "dosage": "75", "unit": "mg",
        "frequency": "once_daily", "times": ["09:00"]})

    card = client.get("/api/medicines/card").get_json()
    slots = {s["time"]: s for s in card["schedule"]}
    assert set(slots) == {"09:00", "21:00"}
    assert slots["09:00"]["label"] == "Morning"
    assert slots["21:00"]["label"] == "Night"
    # 9am slot holds BOTH meds; the med carries its dose + purpose + with_food
    names9 = sorted(m["name"] for m in slots["09:00"]["meds"])
    assert names9 == ["Aspirin", "Metformin"]
    metf = next(m for m in slots["09:00"]["meds"] if m["name"] == "Metformin")
    assert metf["dose"] == "500 mg" and metf["purpose"] == "diabetes" and metf["with_food"] is True
    assert card["count"] == 2


def test_as_needed_med_is_separated_not_scheduled(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "card2@medeasy.test", "password": PW})
    c.post("/api/medicines", json={"name": "Painkiller", "frequency": "as_needed"})
    card = c.get("/api/medicines/card").get_json()
    assert card["schedule"] == []
    assert [m["name"] for m in card["as_needed"]] == ["Painkiller"]
    # No dosage given → dose is blank, never a bare unit like "mg"
    assert card["as_needed"][0]["dose"] == ""


def test_card_includes_emergency_contacts_and_person(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "card3@medeasy.test", "password": PW})
    c.post("/api/emergency", json={
        "blood_type": "O+", "allergies": "Penicillin",
        "contact1_name": "Asha", "contact1_phone": "555-0100",
        "contact2_name": "", "contact2_phone": ""})
    card = c.get("/api/medicines/card").get_json()
    emg = card["emergency"]
    assert emg["blood_type"] == "O+" and emg["allergies"] == "Penicillin"
    # only the filled contact is carried; the blank one is dropped
    assert emg["contacts"] == [{"name": "Asha", "phone": "555-0100"}]
    assert "person" in card and "generated" in card


def test_card_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/medicines/card").status_code == 401
