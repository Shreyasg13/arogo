"""Adherence streak — consecutive 'perfect' days (every scheduled dose taken).

A day with nothing scheduled is neutral (never breaks or pads a run); today is
counted only once complete, and an in-progress today never breaks the streak.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context
from db.medicines import insert_medicine, log_dose, get_adherence_streak

PW = "streak-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    from db.core import execute
    return dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def _day(offset):
    return (dt.date.today() - dt.timedelta(days=offset)).isoformat()


def _daily(name, start_offset=40):
    return insert_medicine({"name": name, "times": ["09:00"],
                            "frequency": "once_daily", "start_date": _day(start_offset)})


def test_no_history_is_zero(app):
    uid = _uid(app, "streak0@medeasy.test")
    with user_context(uid):
        s = get_adherence_streak()
    assert s == {"streak": 0, "best": 0, "perfect_today": False}


def test_counts_consecutive_perfect_days(app):
    uid = _uid(app, "streak1@medeasy.test")
    with user_context(uid):
        m = _daily("StreakMed")
        for i in range(5):                 # took it the last 5 days incl. today
            log_dose(m["id"], _day(i), "09:00", taken=True)
        s = get_adherence_streak()
    assert s["streak"] == 5
    assert s["best"] >= 5
    assert s["perfect_today"] is True


def test_a_miss_breaks_the_streak(app):
    uid = _uid(app, "streak2@medeasy.test")
    with user_context(uid):
        m = _daily("BreakMed")
        for i in range(3):                 # today, -1, -2 taken
            log_dose(m["id"], _day(i), "09:00", taken=True)
        # day -3 missed (not logged); days -4..-6 taken → a prior run of 3
        for i in (4, 5, 6):
            log_dose(m["id"], _day(i), "09:00", taken=True)
        s = get_adherence_streak()
    assert s["streak"] == 3        # current run stops at the -3 miss
    assert s["best"] >= 3


def test_in_progress_today_does_not_break_streak(app):
    uid = _uid(app, "streak3@medeasy.test")
    with user_context(uid):
        m = _daily("TodayPendingMed")
        for i in range(1, 5):              # took days -1..-4, today NOT yet taken
            log_dose(m["id"], _day(i), "09:00", taken=True)
        s = get_adherence_streak()
    # Today is pending (missed-status) but must not break the 4-day run.
    assert s["streak"] == 4
    assert s["perfect_today"] is False
