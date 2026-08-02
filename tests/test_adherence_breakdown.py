"""Per-slot adherence breakdown — 'which doses do I miss most?'."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "brk-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _days_ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_worst_slot_surfaces_and_slots_rank_worst_first(app):
    c = _register(app, "brk1@medeasy.test")
    start = _days_ago(20)
    m = c.post("/api/medicines", json={
        "name": "Metformin", "frequency": "twice_daily",
        "times": ["09:00", "21:00"], "start_date": start}).get_json()["medicine"]
    # Take the 9am dose every day for a week, never the 9pm one.
    for i in range(7):
        c.post(f"/api/medicines/{m['id']}/log",
               json={"date": _days_ago(i), "time": "09:00", "taken": True})

    b = c.get("/api/medicines/adherence-breakdown?days=30").get_json()
    assert b["has_data"] is True
    # 9pm should be the worst (0% taken) and lead the list.
    assert b["worst"]["time"] == "21:00" and b["worst"]["pct"] == 0
    assert b["slots"][0]["time"] == "21:00"
    # the 9am slot has a higher pct than the 9pm slot
    nine_am = next(s for s in b["slots"] if s["time"] == "09:00")
    nine_pm = next(s for s in b["slots"] if s["time"] == "21:00")
    assert nine_am["pct"] > nine_pm["pct"]
    assert nine_pm["missed"] == nine_pm["total"]


def test_slots_below_min_scheduled_are_omitted(app):
    c = _register(app, "brk2@medeasy.test")
    # Course started today → only 1 scheduled day so far, below the min of 3.
    c.post("/api/medicines", json={
        "name": "BrandNew", "frequency": "once_daily", "times": ["08:00"]})
    b = c.get("/api/medicines/adherence-breakdown?days=30").get_json()
    assert b["slots"] == [] and b["has_data"] is False and b["worst"] is None


def test_perfect_adherence_yields_no_headline(app):
    c = _register(app, "brk3@medeasy.test")
    start = _days_ago(10)
    m = c.post("/api/medicines", json={
        "name": "Vitamin", "frequency": "once_daily",
        "times": ["09:00"], "start_date": start}).get_json()["medicine"]
    for i in range(11):
        c.post(f"/api/medicines/{m['id']}/log",
               json={"date": _days_ago(i), "time": "09:00", "taken": True})
    b = c.get("/api/medicines/adherence-breakdown?days=30").get_json()
    assert b["has_data"] is True                 # the slot has enough data...
    assert b["slots"][0]["pct"] == 100
    assert b["worst"] is None                    # ...but nothing was missed


def test_breakdown_requires_auth(app):
    assert app.test_client().get("/api/medicines/adherence-breakdown").status_code == 401
