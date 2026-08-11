"""I2 — travel supply planner. Pills needed per med over a trip, whether stock
covers it, and a refill-before-you-go list. From the med's own schedule + stock;
PRN excluded (no predictable rate to invent)."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import insert_medicine
from db.travel import plan_travel_supply

PW = "trip-pw-123456"


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


def _range(days):
    start = dt.date.today() + dt.timedelta(days=3)
    return start.isoformat(), (start + dt.timedelta(days=days - 1)).isoformat()


def _stock(mid, n):
    """insert_medicine doesn't set pill_count (stock is entered separately)."""
    execute("UPDATE medicines SET pill_count=? WHERE id=?", (n, mid), commit=True)


def test_bad_dates_rejected(app):
    _, uid = _uid(app, "trip1@medeasy.test")
    with user_context(uid):
        assert plan_travel_supply("nope", "2026-01-01")["ok"] is False
        s, e = _range(5)
        assert plan_travel_supply(e, s)["reason"] == "end_before_start"   # reversed


def test_daily_med_needs_two_pills_a_day(app):
    _, uid = _uid(app, "trip2@medeasy.test")
    s, e = _range(10)   # 10-day trip
    with user_context(uid):
        m = insert_medicine({"name": "Amlodipine", "frequency": "twice_daily",
                             "times": ["09:00", "21:00"]})
        _stock(m["id"], 30)
        d = plan_travel_supply(s, e)
    it = d["items"][0]
    assert it["needed"] == 20          # 10 days × 2 doses × 1 pill
    assert it["available"] == 30
    assert it["covered"] is True
    assert it["shortfall"] == 0
    assert d["all_covered"] is True


def test_shortfall_flags_a_refill(app):
    _, uid = _uid(app, "trip3@medeasy.test")
    s, e = _range(20)   # 20-day trip, only 5 pills on hand
    with user_context(uid):
        m = insert_medicine({"name": "Levothyroxine", "frequency": "once_daily",
                             "times": ["07:00"]})
        _stock(m["id"], 5)
        d = plan_travel_supply(s, e)
    it = d["items"][0]
    assert it["needed"] == 20 and it["shortfall"] == 15 and it["covered"] is False
    assert d["all_covered"] is False
    assert d["refill_needed"] and d["refill_needed"][0]["name"] == "Levothyroxine"


def test_prn_excluded(app):
    _, uid = _uid(app, "trip4@medeasy.test")
    s, e = _range(7)
    with user_context(uid):
        insert_medicine({"name": "Ibuprofen", "frequency": "as_needed", "pill_count": 10})
        d = plan_travel_supply(s, e)
    assert d["items"] == []             # PRN never appears — no rate to predict


def test_weekly_schedule_counts_only_those_weekdays(app):
    _, uid = _uid(app, "trip5@medeasy.test")
    # A fixed 14-day window starting on a Monday → exactly 2 Mondays.
    start = dt.date(2026, 8, 17)        # a Monday
    s, e = start.isoformat(), (start + dt.timedelta(days=13)).isoformat()
    with user_context(uid):
        m = insert_medicine({"name": "Methotrexate", "frequency": "once_daily",
                             "times": ["09:00"], "schedule_days": [0]})  # Mondays only
        _stock(m["id"], 8)
        d = plan_travel_supply(s, e)
    assert d["items"][0]["needed"] == 2    # two Mondays in the fortnight


def test_untracked_stock_reports_none(app):
    _, uid = _uid(app, "trip6@medeasy.test")
    s, e = _range(5)
    with user_context(uid):
        insert_medicine({"name": "Aspirin", "frequency": "once_daily", "times": ["08:00"]})
        d = plan_travel_supply(s, e)
    it = d["items"][0]
    assert it["available"] is None and it["covered"] is None and it["shortfall"] is None


def test_api_route(app):
    c, uid = _uid(app, "trip7@medeasy.test")
    s, e = _range(4)
    with user_context(uid):
        m = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["08:00"]})
        _stock(m["id"], 10)
    body = c.get(f"/api/medicines/travel-supply?start={s}&end={e}").get_json()
    assert body["ok"] is True and body["trip_days"] == 4 and body["items"][0]["needed"] == 4
