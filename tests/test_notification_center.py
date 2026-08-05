"""Notification center gaps: account-wide default snooze + per-medicine reminder
lead editable after creation."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute

PW = "notif-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _client(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def test_default_snooze_round_trips(app):
    c = _client(app, "notif1@medeasy.test")
    c.get("/api/reminders/settings")     # create defaults
    assert c.get("/api/reminders/settings").get_json()["default_snooze_min"] == 10   # default
    c.post("/api/reminders/settings", json={"default_snooze_min": 20})
    assert c.get("/api/reminders/settings").get_json()["default_snooze_min"] == 20


def test_default_snooze_is_clamped(app):
    c = _client(app, "notif2@medeasy.test")
    c.get("/api/reminders/settings")
    c.post("/api/reminders/settings", json={"default_snooze_min": 9999})
    assert c.get("/api/reminders/settings").get_json()["default_snooze_min"] == 180   # capped
    c.post("/api/reminders/settings", json={"default_snooze_min": 0})
    assert c.get("/api/reminders/settings").get_json()["default_snooze_min"] == 1     # floor


def test_snooze_without_minutes_uses_default(app):
    c = _client(app, "notif3@medeasy.test")
    c.get("/api/reminders/settings")
    c.post("/api/reminders/settings", json={"default_snooze_min": 25})
    m = c.post("/api/medicines", json={"name": "Amoxicillin", "frequency": "once_daily",
                                       "times": ["09:00"]}).get_json()["medicine"]
    r = c.post(f"/api/medicines/{m['id']}/snooze", json={"time": "09:00"}).get_json()
    assert r["success"] and r["minutes"] == 25     # picked up the user's default


def test_snooze_explicit_minutes_override_default(app):
    c = _client(app, "notif4@medeasy.test")
    c.get("/api/reminders/settings")
    c.post("/api/reminders/settings", json={"default_snooze_min": 25})
    m = c.post("/api/medicines", json={"name": "Ibuprofen", "frequency": "once_daily",
                                       "times": ["09:00"]}).get_json()["medicine"]
    r = c.post(f"/api/medicines/{m['id']}/snooze", json={"time": "09:00", "minutes": 5}).get_json()
    assert r["minutes"] == 5


def test_reminder_lead_editable_after_creation(app):
    c = _client(app, "notif5@medeasy.test")
    m = c.post("/api/medicines", json={"name": "Losartan", "frequency": "once_daily",
                                       "times": ["09:00"], "reminder_lead_min": 0}).get_json()["medicine"]
    assert m["reminder_lead_min"] == 0
    upd = c.post(f"/api/medicines/{m['id']}/reminder-lead", json={"minutes": 45}).get_json()
    assert upd["success"] and upd["medicine"]["reminder_lead_min"] == 45
    # clamp to 120
    upd2 = c.post(f"/api/medicines/{m['id']}/reminder-lead", json={"minutes": 999}).get_json()
    assert upd2["medicine"]["reminder_lead_min"] == 120


def test_reminder_lead_unknown_med_404(app):
    c = _client(app, "notif6@medeasy.test")
    assert c.post("/api/medicines/nope/reminder-lead", json={"minutes": 10}).status_code == 404


def test_reminder_lead_isolation(app):
    c_a = _client(app, "notif7@medeasy.test")
    c_b = _client(app, "notif8@medeasy.test")
    m = c_a.post("/api/medicines", json={"name": "SecretMed", "frequency": "once_daily",
                                         "times": ["09:00"]}).get_json()["medicine"]
    # user B cannot touch user A's medicine
    assert c_b.post(f"/api/medicines/{m['id']}/reminder-lead", json={"minutes": 30}).status_code == 404