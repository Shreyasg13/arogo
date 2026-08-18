"""Today timeline — a single day's logged events in clock order."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db.today_timeline import get_today_timeline, _hm

PW = "ttl-pw-12345"


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


def _ts(hhmm):
    return f"{user_today()}T{hhmm}:00"


def test_hm_extracts_clock():
    assert _hm("2026-08-21T14:30:00") == "14:30"
    assert _hm("nope") == ""


def test_empty(app):
    _, uid = _uid(app, "ttl1@medeasy.test")
    with user_context(uid):
        d = get_today_timeline()
    assert d["events"] == [] and d["count"] == 0
    assert d["today"] == user_today()


def test_stitches_sources_in_clock_order(app):
    _, uid = _uid(app, "ttl2@medeasy.test")
    today = user_today()
    with user_context(uid):
        execute("INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id) VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), today, "blood_pressure", 120, 80, "mmHg", _ts("08:15"), uid), commit=True)
        execute("INSERT INTO food_logs (id,food_name,meal_type,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), "Poha", "breakfast", today, _ts("09:00"), uid), commit=True)
        execute("INSERT INTO hydration_logs (id,amount_ml,drink_type,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), 250, "water", today, _ts("11:30"), uid), commit=True)
        execute("INSERT INTO symptoms (id,name,severity,date_key,time_of_day,logged_at,user_id) VALUES (?,?,?,?,?,?,?)",
                (new_id(), "Headache", 4, today, "morning", _ts("07:45"), uid), commit=True)
        d = get_today_timeline()
    times = [e["time"] for e in d["events"]]
    assert times == sorted(times)                       # clock-ordered
    kinds = {e["kind"] for e in d["events"]}
    assert {"vital", "food", "water", "symptom"} <= kinds
    bp = next(e for e in d["events"] if e["kind"] == "vital")
    assert bp["detail"].startswith("120/80")            # BP shown as systolic/diastolic
    assert next(e for e in d["events"] if e["kind"] == "symptom")["time"] == "07:45"


def test_only_today(app):
    _, uid = _uid(app, "ttl3@medeasy.test")
    with user_context(uid):
        execute("INSERT INTO food_logs (id,food_name,meal_type,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), "Yesterday meal", "lunch", "2020-01-01", "2020-01-01T12:00:00", uid), commit=True)
        d = get_today_timeline()
    assert all("Yesterday" not in e["title"] for e in d["events"])


def test_isolation(app):
    _, a = _uid(app, "ttl4a@medeasy.test")
    _, b = _uid(app, "ttl4b@medeasy.test")
    today = user_today()
    with user_context(a):
        execute("INSERT INTO hydration_logs (id,amount_ml,drink_type,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), 300, "water", today, _ts("10:00"), a), commit=True)
    with user_context(b):
        d = get_today_timeline()
    assert d["events"] == []                            # B never sees A's water


def test_route(app):
    c, _ = _uid(app, "ttl5@medeasy.test")
    body = c.get("/api/today-timeline").get_json()
    assert "events" in body and "today" in body


def test_route_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/today-timeline").status_code in (401, 403)
