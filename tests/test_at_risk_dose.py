"""At-risk dose — of today's pending doses, the one most often missed before."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute

PW = "risk-pw-12345"


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


def _med(c, name, times, start_days_ago=40):
    start = (dt.date.today() - dt.timedelta(days=start_days_ago)).isoformat()
    freq = {1: "once_daily", 2: "twice_daily"}.get(len(times), "custom")
    return c.post("/api/medicines", json={
        "name": name, "frequency": freq, "times": times, "start_date": start}).get_json()["medicine"]["id"]


def _risk(c):
    return c.get("/api/medicines/at-risk").get_json()["at_risk"]


def test_none_when_no_history(app):
    c = _client(app, "risk1@medeasy.test")
    _med(c, "FreshMed", ["09:00"], start_days_ago=0)   # starts today → no prior scheduled days
    assert _risk(c) is None               # below min_history, nothing to judge


def test_flags_the_frequently_missed_pending_dose(app):
    c = _client(app, "risk2@medeasy.test")
    mid = _med(c, "Statin", ["21:00"])
    # Historically take it only ~20% of days over the last 30 → high miss rate.
    for i in range(1, 31):
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        if i % 5 == 0:                    # taken 6 of 30 days
            c.post(f"/api/medicines/{mid}/log", json={"date": d, "time": "21:00", "taken": True})
    r = _risk(c)                          # today's 21:00 dose is still pending
    assert r is not None
    assert r["med_name"] == "Statin" and r["time"] == "21:00"
    assert r["miss_pct"] >= 25 and r["scheduled"] == 30


def test_taken_today_is_not_at_risk(app):
    c = _client(app, "risk3@medeasy.test")
    mid = _med(c, "BP Med", ["08:00"])
    for i in range(1, 31):                # miss most days historically
        pass
    today = dt.date.today().isoformat()
    c.post(f"/api/medicines/{mid}/log", json={"date": today, "time": "08:00", "taken": True})
    assert _risk(c) is None               # already taken → not pending → not at risk


def test_well_taken_dose_not_flagged(app):
    c = _client(app, "risk4@medeasy.test")
    mid = _med(c, "GoodMed", ["07:00"])
    for i in range(1, 31):                # taken almost every day → low miss rate
        d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        c.post(f"/api/medicines/{mid}/log", json={"date": d, "time": "07:00", "taken": True})
    assert _risk(c) is None               # below the risk threshold
