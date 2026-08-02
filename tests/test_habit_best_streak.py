"""Habit trends: all-time best (longest) streak."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "hb-pw-1234567"


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


def _ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_best_streak_is_longest_run_even_after_a_break(app):
    c = _register(app, "hb1@medeasy.test")
    hid = c.post("/api/habits", json={"name": "Walk", "emoji": "🚶", "color": "#4F8D74"}).get_json()["habit"]["id"]
    # A 5-day run three weeks ago, broken, then a shorter recent run.
    for n in (25, 24, 23, 22, 21):
        c.post(f"/api/habits/{hid}/toggle", json={"date_key": _ago(n)})
    for n in (2, 1, 0):
        c.post(f"/api/habits/{hid}/toggle", json={"date_key": _ago(n)})

    me = next(x for x in c.get("/api/habits").get_json()["habits"] if x["id"] == hid)
    assert me["best_streak"] == 5           # the old 5-run is still the personal best
    assert me["streak"] <= 3                 # current streak is the recent run


def test_no_completions_means_zero_best_streak(app):
    c = _register(app, "hb2@medeasy.test")
    hid = c.post("/api/habits", json={"name": "Read", "emoji": "📖", "color": "#5E8299"}).get_json()["habit"]["id"]
    me = next(x for x in c.get("/api/habits").get_json()["habits"] if x["id"] == hid)
    assert me["best_streak"] == 0
