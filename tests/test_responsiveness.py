"""Reminder responsiveness — how soon taken doses get logged after they're due."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.medicines import get_reminder_responsiveness, insert_medicine

PW = "resp-pw-12345"


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


def _dose(uid, mid, date_key, time_key, taken_at):
    """Insert a taken dose_log with a specific taken_at timestamp."""
    execute("""INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id)
               VALUES (?,?,?,?,1,?,?)""",
            (new_id(), mid, date_key, time_key, taken_at, uid), commit=True)


def test_empty_without_doses(app):
    _, uid = _uid(app, "resp1@medeasy.test")
    with user_context(uid):
        d = get_reminder_responsiveness()
    assert d["has_data"] is False and d["median_delay_min"] is None


def test_buckets_and_median(app):
    _, uid = _uid(app, "resp2@medeasy.test")
    day = dt.date.today().isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        _dose(uid, mid, day, "09:00", f"{day}T09:10:00")   # +10 min → on time
        _dose(uid, mid, day, "12:00", f"{day}T13:30:00")   # +90 min → late
        _dose(uid, mid, day, "18:00", f"{day}T17:50:00")   # -10 min → early
        _dose(uid, mid, day, "20:00", f"{day}T23:40:00")   # +220 min → very late
        d = get_reminder_responsiveness()
    b = {x["key"]: x["count"] for x in d["buckets"]}
    assert b["ontime"] == 1 and b["late"] == 1 and b["early"] == 1 and b["very_late"] == 1
    assert d["count"] == 4
    assert d["median_delay_min"] == 50    # median of [-10, 10, 90, 220]
    assert d["ontime_pct"] == 50           # early + on-time = 2 of 4


def test_backfill_excluded(app):
    _, uid = _uid(app, "resp3@medeasy.test")
    day = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    logged = dt.date.today().isoformat()               # logged 10 days later
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        _dose(uid, uid and mid, day, "09:00", f"{logged}T09:00:00")   # |Δ| ~10 days → excluded
        d = get_reminder_responsiveness()
    assert d["has_data"] is False


def test_api(app):
    c, uid = _uid(app, "resp4@medeasy.test")
    day = dt.date.today().isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        _dose(uid, mid, day, "09:00", f"{day}T09:05:00")
    body = c.get("/api/medicines/adherence/responsiveness").get_json()
    assert body["has_data"] is True and body["ontime_pct"] == 100
