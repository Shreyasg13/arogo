"""D custom health reminders — the user's own list of health to-dos with a due
date and optional repeat. User-defined only (no app-recommended schedules);
ticking a repeat rolls the date forward, a one-off is done. User-scoped."""
import datetime as dt
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db

PW = "hr-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client(); c.post("/auth/register", json={"email": email, "password": PW}); return c


def _days(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_add_and_overdue_flag(app):
    c = _reg(app, "hr1@medeasy.test")
    c.post("/api/health-reminders", json={"title": "Eye test", "due_date": _days(-3)})
    c.post("/api/health-reminders", json={"title": "Dental cleaning", "due_date": _days(20)})
    rem = c.get("/api/health-reminders").get_json()["reminders"]
    assert len(rem) == 2
    eye = next(r for r in rem if r["title"] == "Eye test")
    assert eye["overdue"] is True and eye["days_until"] == -3


def test_title_and_date_required(app):
    c = _reg(app, "hr2@medeasy.test")
    assert c.post("/api/health-reminders", json={"title": "", "due_date": _days(1)}).status_code == 400
    assert c.post("/api/health-reminders", json={"title": "X", "due_date": "soon"}).status_code == 400


def test_repeat_rolls_forward_on_done(app):
    c = _reg(app, "hr3@medeasy.test")
    r = c.post("/api/health-reminders", json={"title": "Annual physical", "due_date": _days(-5), "repeat_days": 365}).get_json()["reminder"]
    assert r["recurring"] is True and r["overdue"] is True
    done = c.post(f"/api/health-reminders/{r['id']}/done").get_json()["reminder"]
    # Rolled to ~a year from today, no longer overdue, still active.
    assert done["overdue"] is False and done["done"] == 0 and done["days_until"] > 300


def test_oneoff_is_ticked_off(app):
    c = _reg(app, "hr4@medeasy.test")
    r = c.post("/api/health-reminders", json={"title": "Book scan", "due_date": _days(2)}).get_json()["reminder"]
    c.post(f"/api/health-reminders/{r['id']}/done")
    assert c.get("/api/health-reminders").get_json()["reminders"] == []   # done ones drop off the active list


def test_blank_repeat_stays_null(app):
    c = _reg(app, "hr5@medeasy.test")
    r = c.post("/api/health-reminders", json={"title": "One time", "due_date": _days(1), "repeat_days": ""}).get_json()["reminder"]
    assert r["repeat_days"] is None and r["recurring"] is False


def test_user_scoped(app):
    a = _reg(app, "hr6a@medeasy.test"); b = _reg(app, "hr6b@medeasy.test")
    r = a.post("/api/health-reminders", json={"title": "Private", "due_date": _days(1)}).get_json()["reminder"]
    assert b.get("/api/health-reminders").get_json()["reminders"] == []
    assert b.post(f"/api/health-reminders/{r['id']}/done").status_code == 404


def test_requires_auth(app):
    assert app.test_client().get("/api/health-reminders").status_code in (401, 403)
