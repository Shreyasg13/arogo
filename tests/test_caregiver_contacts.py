"""Tests for zero-install caregiver alert contacts (SMS/WhatsApp, no account).

Covers the route + data layer: adding a phone contact, phone normalization,
per-user isolation, and the honest dev-mode "test" send.
"""
import pytest

import auth as auth_module
from db.core import init_db
from app import create_app

PW = "care-pw-12345"


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


def _client(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def test_add_list_toggle_delete(app):
    c = _client(app, "care1@medeasy.test")
    r = c.post("/api/family/alert-contacts",
               json={"name": "Mom", "phone": "+91 98123 45678", "channel": "sms"})
    assert r.status_code == 200
    contact = r.get_json()["contact"]
    assert contact["phone"] == "+919812345678"      # normalized to E.164
    assert contact["name"] == "Mom"
    cid = contact["id"]

    d = c.get("/api/family/alert-contacts").get_json()
    assert any(x["id"] == cid for x in d["contacts"])
    assert d["sms_live"] is False                    # no provider configured in tests

    assert c.patch(f"/api/family/alert-contacts/{cid}",
                   json={"alerts_enabled": False}).status_code == 200
    assert c.delete(f"/api/family/alert-contacts/{cid}").status_code == 200
    d2 = c.get("/api/family/alert-contacts").get_json()
    assert not any(x["id"] == cid for x in d2["contacts"])


def test_phone_needs_country_code(app):
    c = _client(app, "care2@medeasy.test")
    r = c.post("/api/family/alert-contacts", json={"name": "Dad", "phone": "9812345678"})
    assert r.status_code == 400
    assert "country code" in r.get_json()["error"].lower()


def test_name_required(app):
    c = _client(app, "care3@medeasy.test")
    r = c.post("/api/family/alert-contacts", json={"name": "", "phone": "+14155550100"})
    assert r.status_code == 400


def test_whatsapp_channel(app):
    c = _client(app, "care4@medeasy.test")
    r = c.post("/api/family/alert-contacts",
               json={"name": "Sis", "phone": "+14155550100", "channel": "whatsapp"})
    assert r.get_json()["contact"]["channel"] == "whatsapp"


def test_contacts_are_per_user(app):
    a = _client(app, "care5@medeasy.test")
    b = _client(app, "care6@medeasy.test")
    a.post("/api/family/alert-contacts", json={"name": "OnlyA", "phone": "+14155550111"})
    d = b.get("/api/family/alert-contacts").get_json()
    assert not any(x["name"] == "OnlyA" for x in d["contacts"])


def test_test_endpoint_reports_dev_mode(app):
    c = _client(app, "care7@medeasy.test")
    cid = c.post("/api/family/alert-contacts",
                 json={"name": "Mom", "phone": "+14155550100"}).get_json()["contact"]["id"]
    d = c.post(f"/api/family/alert-contacts/{cid}/test").get_json()
    assert d["success"] is True
    # No Twilio configured in tests → simulated, never claims delivery
    assert d["dev_mode"] is True and d["delivered"] is False
