"""Recent-trend adherence nudge — the last-7-days 'what's slipping now' signal
that complements the 30-day 'which doses do I miss most' breakdown.

Honesty bar: only fires with enough recent scheduled doses, stays silent when
recent adherence is fine, and every count comes from real dose logs.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context
from db.medicines import insert_medicine, log_dose, get_adherence_nudge

PW = "nudge-pw-12345"


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


def _add_daily(name):
    old_start = _day(30)
    return insert_medicine({"name": name, "times": ["09:00"],
                            "frequency": "once_daily", "start_date": old_start})


def test_silent_with_no_data(app):
    uid = _uid(app, "nudge0@medeasy.test")
    with user_context(uid):
        assert get_adherence_nudge()["kind"] is None


def test_silent_when_recent_adherence_is_fine(app):
    uid = _uid(app, "nudge1@medeasy.test")
    with user_context(uid):
        m = _add_daily("GoodMed")
        for i in range(7):              # took it every day this week
            log_dose(m["id"], _day(i), "09:00", taken=True)
        assert get_adherence_nudge()["kind"] is None


def test_recent_misses_names_the_slot(app):
    uid = _uid(app, "nudge2@medeasy.test")
    with user_context(uid):
        m = _add_daily("MissyMed")
        log_dose(m["id"], _day(0), "09:00", taken=True)   # took it once
        # days 1..6 left unlogged → missed 6 of 7
        n = get_adherence_nudge()
    assert n["kind"] == "recent_misses"
    assert n["med_name"] == "MissyMed"
    assert n["time"] == "09:00"
    assert n["scheduled"] == 7 and n["missed"] == 6


def test_slipping_beats_recent_misses(app):
    uid = _uid(app, "nudge3@medeasy.test")
    with user_context(uid):
        m = _add_daily("SlipMed")
        for i in range(7, 14):          # prior week: took every day
            log_dose(m["id"], _day(i), "09:00", taken=True)
        log_dose(m["id"], _day(0), "09:00", taken=True)   # this week: only once
        n = get_adherence_nudge()
    assert n["kind"] == "slipping"
    assert n["prev_pct"] == 100
    assert n["recent_pct"] <= 50


def test_thin_data_below_min_recent_stays_silent(app):
    uid = _uid(app, "nudge4@medeasy.test")
    with user_context(uid):
        # Only in course for the last 2 days → fewer than min_recent (3) scheduled.
        m = insert_medicine({"name": "NewMed", "times": ["09:00"],
                             "frequency": "once_daily", "start_date": _day(1)})
        n = get_adherence_nudge()
    assert n["kind"] is None
