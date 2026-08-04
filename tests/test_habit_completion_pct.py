"""Habit-completion percentages must never exceed 100%.

Regression for a window mismatch: get_habit_stats() spans 30 days, but the
weekly report divided its done-day count by 7, and the monthly view divided the
same 30-day count by days-elapsed-this-month — so a habit kept for a couple of
weeks read 114% (weekly) or 200% (monthly)."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.insights import generate_weekly_report, get_goal_progress

PW = "hpct-pw-12345"


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


def _ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_completion_never_exceeds_100pct(app):
    c, uid = _uid(app, "hpct1@medeasy.test")
    hid = c.post("/api/habits", json={"name": "Stretch", "emoji": "🤸", "color": "#4F8D74"}).get_json()["habit"]["id"]
    # Completed on each of the last 12 days — spans well past a 7-day window and,
    # early in a month, past days-elapsed. The buggy math read >100% here.
    for n in range(12):
        c.post(f"/api/habits/{hid}/toggle", json={"date_key": _ago(n)})

    with user_context(uid):
        weekly = generate_weekly_report()
        monthly = get_goal_progress()

    wk = weekly["habits"]["completion_pct"]
    mo = monthly["habits"]["completion_pct"]
    assert wk is not None and 0 < wk <= 100, f"weekly habit completion out of range: {wk}"
    assert 0 < mo <= 100, f"monthly habit completion out of range: {mo}"


def test_weekly_completion_counts_only_the_last_7_days(app):
    c, uid = _uid(app, "hpct2@medeasy.test")
    hid = c.post("/api/habits", json={"name": "Read", "emoji": "📖", "color": "#4F8D74"}).get_json()["habit"]["id"]
    # 3 of the last 7 days done, plus older ones outside the window.
    for n in (0, 1, 2):          # inside the 7-day window
        c.post(f"/api/habits/{hid}/toggle", json={"date_key": _ago(n)})
    for n in (10, 12, 20):       # outside it — must not inflate the weekly figure
        c.post(f"/api/habits/{hid}/toggle", json={"date_key": _ago(n)})

    with user_context(uid):
        weekly = generate_weekly_report()
    # 3 done / (1 habit * 7 days) = ~42.9%
    assert weekly["habits"]["completion_pct"] == pytest.approx(42.9, abs=0.5)


def test_perfect_week_is_exactly_100(app):
    c, uid = _uid(app, "hpct3@medeasy.test")
    hid = c.post("/api/habits", json={"name": "Water", "emoji": "💧", "color": "#4F8D74"}).get_json()["habit"]["id"]
    for n in range(7):           # every day of the last 7
        c.post(f"/api/habits/{hid}/toggle", json={"date_key": _ago(n)})

    with user_context(uid):
        weekly = generate_weekly_report()
    assert weekly["habits"]["completion_pct"] == 100
