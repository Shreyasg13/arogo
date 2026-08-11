"""I4 — adherence by weekday. The 'weekends slip' cut the time-of-day view
can't show. Same scheduling rules as the time-of-day breakdown, grouped Mon–Sun.
From the user's own dose history; no invented days."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.medicines import insert_medicine, get_adherence_by_weekday

PW = "wd-pw-1234567"


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


def _take(uid, mid, day, time_key):
    execute("""INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,taken_at,user_id)
               VALUES (?,?,?,?,1,?,?)""",
            (new_id(), mid, day, time_key, f"{day}T{time_key}:00", uid), commit=True)


def test_empty_without_meds(app):
    _, uid = _uid(app, "wd1@medeasy.test")
    with user_context(uid):
        d = get_adherence_by_weekday()
    assert d["has_data"] is False and d["worst"] is None


def test_groups_by_weekday_and_finds_worst(app):
    _, uid = _uid(app, "wd2@medeasy.test")
    today = dt.date.today()
    old_start = (today - dt.timedelta(days=120)).isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily",
                               "times": ["09:00"], "start_date": old_start})["id"]
        # Over the last 90 days, take every scheduled dose EXCEPT on Sundays.
        for i in range(90):
            day = today - dt.timedelta(days=i)
            if day.weekday() != 6:                       # skip Sundays → misses pile up there
                _take(uid, mid, day.isoformat(), "09:00")
        d = get_adherence_by_weekday(days=90)
    assert d["has_data"] is True
    assert d["worst"] == 6                                # Sunday is the hardest day
    sun = next(w for w in d["weekdays"] if w["weekday"] == 6)
    mon = next(w for w in d["weekdays"] if w["weekday"] == 0)
    assert sun["pct"] == 0.0 and mon["pct"] == 100.0
    assert sun["missed"] == sun["total"]


def test_low_volume_day_is_not_crowned_worst(app):
    _, uid = _uid(app, "wd3@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        # A med scheduled ONLY on Mondays, all taken → the other days have 0
        # scheduled doses and must never be named 'worst'.
        mid = insert_medicine({"name": "Wk", "frequency": "once_daily", "times": ["09:00"],
                               "schedule_days": [0],
                               "start_date": (today - dt.timedelta(days=120)).isoformat()})["id"]
        for i in range(90):
            day = today - dt.timedelta(days=i)
            if day.weekday() == 0:
                _take(uid, mid, day.isoformat(), "09:00")
        d = get_adherence_by_weekday(days=90)
    # Only Mondays had doses, all taken → no eligible 'worst'.
    assert d["worst"] is None
    non_monday_totals = [w["total"] for w in d["weekdays"] if w["weekday"] != 0]
    assert set(non_monday_totals) == {0}


def test_api(app):
    c, uid = _uid(app, "wd4@medeasy.test")
    today = dt.date.today()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["08:00"]})["id"]
        _take(uid, mid, today.isoformat(), "08:00")
    body = c.get("/api/medicines/adherence/weekday?days=90").get_json()
    assert body["has_data"] is True and len(body["weekdays"]) == 7
