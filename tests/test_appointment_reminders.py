"""Configurable appointment reminder lead-time — the stored field + the pure
phase logic the scheduler uses."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import create_appointment, update_appointment
from scheduler import appt_reminder_phase

PW = "appt-pw-12345"


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


# ── Pure phase logic ─────────────────────────────────────────────────────────

def test_phase_morning_of():
    assert appt_reminder_phase("2026-09-10", 1, "2026-09-10") == "day"


def test_phase_advance_default_one_day():
    assert appt_reminder_phase("2026-09-10", 1, "2026-09-09") == "pre"
    assert appt_reminder_phase("2026-09-10", 1, "2026-09-08") is None


def test_phase_advance_week():
    assert appt_reminder_phase("2026-09-10", 7, "2026-09-03") == "pre"
    assert appt_reminder_phase("2026-09-10", 7, "2026-09-09") is None   # only fires 7d out + day-of


def test_phase_zero_lead_only_morning_of():
    assert appt_reminder_phase("2026-09-10", 0, "2026-09-09") is None
    assert appt_reminder_phase("2026-09-10", 0, "2026-09-10") == "day"


def test_phase_bad_reminder_days_defaults_to_one():
    assert appt_reminder_phase("2026-09-10", None, "2026-09-09") == "pre"


# ── Stored field ─────────────────────────────────────────────────────────────

def test_create_stores_reminder_days(app):
    _, uid = _uid(app, "apptrem1@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "Cardiology", "date": "2026-12-01", "reminder_days": 3})
    assert a["reminder_days"] == 3


def test_reminder_days_defaults_and_clamps(app):
    _, uid = _uid(app, "apptrem2@medeasy.test")
    with user_context(uid):
        d = create_appointment({"title": "A", "date": "2026-12-01"})
        assert d["reminder_days"] == 1                       # default
        big = create_appointment({"title": "B", "date": "2026-12-01", "reminder_days": 999})
        assert big["reminder_days"] == 30                    # clamped
        bad = create_appointment({"title": "C", "date": "2026-12-01", "reminder_days": "x"})
        assert bad["reminder_days"] == 1                     # non-numeric → default


def test_update_reminder_days(app):
    _, uid = _uid(app, "apptrem3@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "A", "date": "2026-12-01", "reminder_days": 1})
        upd = update_appointment(a["id"], {"reminder_days": 7})
        assert upd["reminder_days"] == 7
        # unrelated edit keeps the value
        upd2 = update_appointment(a["id"], {"title": "A2"})
        assert upd2["reminder_days"] == 7


def test_api_round_trip(app):
    c, uid = _uid(app, "apptrem4@medeasy.test")
    r = c.post("/api/appointments", json={"title": "Lab", "date": "2026-12-05", "reminder_days": 2})
    assert r.status_code == 200 and r.get_json()["appointment"]["reminder_days"] == 2
