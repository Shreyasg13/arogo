"""Dose calendar: per-day taken/missed/partial/none status."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "cal-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "cal@medeasy.test", "password": PW})
    return c


def test_calendar_reflects_taken_missed_and_partial(client):
    # twice-daily med, started a week ago so past days are in-course
    start = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    m = client.post("/api/medicines", json={
        "name": "Metformin", "dosage": "500", "unit": "mg", "start_date": start,
        "frequency": "twice_daily", "times": ["09:00", "21:00"]}).get_json()["medicine"]
    today = dt.date.today().isoformat()
    yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()

    # today: both taken → 'all'
    client.post(f"/api/medicines/{m['id']}/log", json={"date": today, "time": "09:00", "taken": True})
    client.post(f"/api/medicines/{m['id']}/log", json={"date": today, "time": "21:00", "taken": True})
    # yesterday: one taken → 'partial'
    client.post(f"/api/medicines/{m['id']}/log", json={"date": yday, "time": "09:00", "taken": True})

    cal = {d["date"]: d for d in client.get("/api/medicines/calendar?days=10").get_json()["days"]}
    assert cal[today]["status"] == "all" and cal[today]["taken"] == 2 and cal[today]["total"] == 2
    assert cal[yday]["status"] == "partial" and cal[yday]["taken"] == 1
    # a day with nothing logged is 'missed' (doses were due, none taken)
    two_ago = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    assert cal[two_ago]["status"] == "missed"


def test_calendar_is_oldest_to_newest_and_bounded(client):
    days = client.get("/api/medicines/calendar?days=35").get_json()["days"]
    assert len(days) == 35
    assert days[0]["date"] < days[-1]["date"]                 # chronological
    assert days[-1]["date"] == dt.date.today().isoformat()    # ends today


def test_as_needed_med_never_marks_a_day_missed(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "cal2@medeasy.test", "password": PW})
    c.post("/api/medicines", json={"name": "Painkiller", "frequency": "as_needed"})
    # No scheduled doses at all → every day is 'none', never 'missed'.
    days = c.get("/api/medicines/calendar?days=7").get_json()["days"]
    assert all(d["status"] == "none" for d in days)
