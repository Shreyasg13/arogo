"""Adherence grouped by part of day — which dose slot the user struggles with."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute
from db.medicines import _time_bucket

PW = "tod-pw-12345"


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


def test_time_bucket_boundaries():
    assert _time_bucket("08:00") == "morning"
    assert _time_bucket("12:00") == "afternoon"
    assert _time_bucket("17:00") == "evening"
    assert _time_bucket("21:00") == "night"
    assert _time_bucket("02:00") == "night"       # wraps past midnight
    assert _time_bucket("04:59") == "night"
    assert _time_bucket("05:00") == "morning"
    assert _time_bucket("garbage") == "morning"   # never raises


def _med(c, name, times, start_days_ago=20):
    start = (dt.date.today() - dt.timedelta(days=start_days_ago)).isoformat()
    freq = {1: "once_daily", 2: "twice_daily"}.get(len(times), "custom")
    return c.post("/api/medicines", json={
        "name": name, "frequency": freq, "times": times, "start_date": start}).get_json()["medicine"]["id"]


def test_buckets_split_and_worst_is_lowest(app):
    c = _client(app, "tod1@medeasy.test")
    mid = _med(c, "TwiceMed", ["09:00", "21:00"])   # morning + night
    today = dt.date.today().isoformat()
    yday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    # Take the morning doses, skip the night ones → night should be the worst.
    for d in (today, yday):
        c.post(f"/api/medicines/{mid}/log", json={"date": d, "time": "09:00", "taken": True})
    for i in range(2, 10):        # take mornings on more days too
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        c.post(f"/api/medicines/{mid}/log", json={"date": d, "time": "09:00", "taken": True})

    data = c.get("/api/medicines/adherence/timeofday?days=20").get_json()
    b = {x["bucket"]: x for x in data["buckets"]}
    assert b["morning"]["taken"] >= 10 and b["morning"]["pct"] > b["night"]["pct"]
    assert b["night"]["taken"] == 0 and b["night"]["missed"] > 0
    assert data["worst"] == "night"
    assert data["has_data"] is True


def test_no_data_has_no_worst(app):
    c = _client(app, "tod2@medeasy.test")
    data = c.get("/api/medicines/adherence/timeofday").get_json()
    assert data["has_data"] is False and data["worst"] is None


def test_worst_needs_minimum_doses(app):
    c = _client(app, "tod3@medeasy.test")
    # A med scheduled only today → 1 dose in the evening bucket, below the floor.
    _med(c, "NewMed", ["18:00"], start_days_ago=0)
    data = c.get("/api/medicines/adherence/timeofday?days=1").get_json()
    ev = next(x for x in data["buckets"] if x["bucket"] == "evening")
    assert ev["total"] == 1
    assert data["worst"] is None      # too few doses to crown a worst
