"""Reminder quiet hours + per-medicine reminder lead time."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db
from scheduler import in_quiet_hours, reminder_offset_min

PW = "qh-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


# ── Pure scheduler helpers ────────────────────────────────────────────────────

def test_quiet_window_that_wraps_past_midnight():
    # 22:00 → 07:00 covers late night and early morning, not midday.
    assert in_quiet_hours("22:00", "07:00", "23:30") is True
    assert in_quiet_hours("22:00", "07:00", "03:00") is True
    assert in_quiet_hours("22:00", "07:00", "06:59") is True
    assert in_quiet_hours("22:00", "07:00", "07:00") is False   # end is exclusive
    assert in_quiet_hours("22:00", "07:00", "13:00") is False


def test_quiet_window_same_day_and_degenerate():
    assert in_quiet_hours("13:00", "14:00", "13:30") is True
    assert in_quiet_hours("13:00", "14:00", "12:59") is False
    assert in_quiet_hours("09:00", "09:00", "09:00") is False   # zero-length = off
    assert in_quiet_hours("bad", "data", "09:00") is False


def test_reminder_lead_shifts_when_a_dose_is_due():
    # A 09:00 dose with a 15-min lead is "due" from 08:45.
    assert reminder_offset_min("09:00", 15, "08:45") == 0        # exactly due
    assert reminder_offset_min("09:00", 15, "08:40") == -5       # not yet
    assert reminder_offset_min("09:00", 15, "09:00") == 15       # 15 past its lead point
    assert reminder_offset_min("09:00", 0,  "09:00") == 0        # no lead
    assert reminder_offset_min("bad",   15, "09:00") is None


# ── Persistence through the settings API ──────────────────────────────────────

def test_quiet_settings_round_trip(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "qh@medeasy.test", "password": PW})
    c.get("/api/reminders/settings")     # create defaults
    c.post("/api/reminders/settings", json={
        "quiet_enabled": 1, "quiet_start": "23:00", "quiet_end": "06:30"})
    s = c.get("/api/reminders/settings").get_json()
    assert s["quiet_enabled"] == 1 and s["quiet_start"] == "23:00" and s["quiet_end"] == "06:30"


def test_reminder_lead_min_stored_on_medicine(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "qh2@medeasy.test", "password": PW})
    m = c.post("/api/medicines", json={
        "name": "Ramipril", "frequency": "once_daily", "times": ["09:00"],
        "reminder_lead_min": 30}).get_json()["medicine"]
    assert m["reminder_lead_min"] == 30
    dose = next(d for d in c.get("/api/medicines/today").get_json() if d["med_id"] == m["id"])
    assert dose["reminder_lead_min"] == 30


def test_reminder_lead_min_is_clamped(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "qh3@medeasy.test", "password": PW})
    m = c.post("/api/medicines", json={
        "name": "Weird", "frequency": "once_daily", "times": ["09:00"],
        "reminder_lead_min": 9999}).get_json()["medicine"]
    assert m["reminder_lead_min"] == 120        # capped at 2 hours
