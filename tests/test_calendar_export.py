"""I1 — iCalendar (.ics) export of dose times, appointments, and lab rechecks.

Everything on the calendar must come from the user's own entries; the format
must be valid enough for Google/Apple/Outlook to import (CRLF lines, escaped
text, RRULE for recurring doses, VALUE=DATE for all-day events)."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.medicines import insert_medicine
from db.health import create_appointment

PW = "cal-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _client(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]
    return c, uid


def test_requires_auth(app):
    assert app.test_client().get("/api/calendar.ics").status_code in (401, 403)


def test_content_type_and_envelope(app):
    c, _ = _client(app, "icsexp1@medeasy.test")
    r = c.get("/api/calendar.ics")
    assert r.status_code == 200
    assert "text/calendar" in r.headers.get("Content-Type", "")
    assert "attachment" in r.headers.get("Content-Disposition", "")
    body = r.get_data(as_text=True)
    assert body.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in body
    assert "\r\n" in body            # RFC 5545 mandates CRLF


def test_scheduled_med_becomes_a_recurring_event(app):
    c, uid = _client(app, "icsexp2@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Metformin", "dosage": "500", "unit": "mg",
                         "frequency": "twice_daily", "times": ["09:00", "21:00"]})
    body = c.get("/api/calendar.ics").get_data(as_text=True)
    assert body.count("BEGIN:VEVENT") == 2          # one per dose time
    assert "RRULE:FREQ=DAILY" in body
    assert "SUMMARY:💊 Metformin (500 mg)" in body
    assert "DTSTART:" in body and "T090000" in body and "T210000" in body


def test_prn_med_is_not_on_the_calendar(app):
    c, uid = _client(app, "icsexp3@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Paracetamol", "frequency": "as_needed"})
    body = c.get("/api/calendar.ics").get_data(as_text=True)
    assert "BEGIN:VEVENT" not in body   # PRN has no clock time — nothing to schedule


def test_weekly_schedule_uses_byday(app):
    c, uid = _client(app, "icsexp4@medeasy.test")
    with user_context(uid):
        # Mon/Wed/Fri = weekday ints 0,2,4
        insert_medicine({"name": "Vitamin D", "frequency": "once_daily",
                         "times": ["08:00"], "schedule_days": [0, 2, 4]})
    body = c.get("/api/calendar.ics").get_data(as_text=True)
    assert "FREQ=WEEKLY;BYDAY=MO,WE,FR" in body


def test_appointment_appears_as_event(app):
    c, uid = _client(app, "icsexp5@medeasy.test")
    future = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    with user_context(uid):
        create_appointment({"title": "Dr. Rao, cardiology", "date": future, "time": "10:30"})
    body = c.get("/api/calendar.ics").get_data(as_text=True)
    # Comma in the title must be escaped so it isn't read as a param separator.
    assert "SUMMARY:🩺 Dr. Rao\\, cardiology" in body
    assert future.replace("-", "") + "T103000" in body


def test_all_day_appointment_without_time(app):
    c, uid = _client(app, "icsexp6@medeasy.test")
    future = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    with user_context(uid):
        create_appointment({"title": "Fasting bloodwork", "date": future})
    body = c.get("/api/calendar.ics").get_data(as_text=True)
    assert "DTSTART;VALUE=DATE:" + future.replace("-", "") in body


def test_lab_recheck_due_date_is_an_event(app):
    c, uid = _client(app, "icsexp7@medeasy.test")
    with user_context(uid):
        # A result 100 days ago with a 90-day recheck → a next-due date exists.
        old = (dt.date.today() - dt.timedelta(days=100)).isoformat()
        execute("""INSERT INTO lab_results (id,user_id,lab_key,name,value,date_key,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), uid, "hba1c", "HbA1c", 6.2, old, old), commit=True)
        execute("""INSERT INTO lab_rechecks (id,user_id,lab_key,interval_days,created_at)
                   VALUES (?,?,?,?,?)""",
                (new_id(), uid, "hba1c", 90, old), commit=True)
    body = c.get("/api/calendar.ics").get_data(as_text=True)
    assert "recheck due" in body
