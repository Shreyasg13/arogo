"""Dose-timing hygiene — same-time meds with conflicting food instructions."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import get_timing_conflicts

PW = "tc-pw-123456"


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


def _med(c, name, times, timing=""):
    return c.post("/api/medicines", json={"name": name, "frequency": "once_daily",
                                          "times": times, "timing": timing}).get_json()["medicine"]


def test_conflict_detected(app):
    c, uid = _uid(app, "tc1@medeasy.test")
    _med(c, "Levothyroxine", ["08:00"], "empty_stomach")
    _med(c, "Metformin", ["08:00"], "with_food")
    with user_context(uid):
        conflicts = get_timing_conflicts()
    assert len(conflicts) == 1
    c0 = conflicts[0]
    assert c0["time"] == "08:00"
    assert c0["with_food"][0]["name"] == "Metformin"
    assert c0["without_food"][0]["name"] == "Levothyroxine"


def test_no_conflict_different_times(app):
    c, uid = _uid(app, "tc2@medeasy.test")
    _med(c, "A", ["08:00"], "empty_stomach")
    _med(c, "B", ["20:00"], "with_food")
    with user_context(uid):
        assert get_timing_conflicts() == []


def test_no_conflict_same_instruction(app):
    c, uid = _uid(app, "tc3@medeasy.test")
    _med(c, "A", ["09:00"], "with_food")
    _med(c, "B", ["09:00"], "with_food")
    with user_context(uid):
        assert get_timing_conflicts() == []


def test_untimed_meds_ignored(app):
    c, uid = _uid(app, "tc4@medeasy.test")
    _med(c, "A", ["09:00"], "")               # no timing instruction
    _med(c, "B", ["09:00"], "with_food")
    with user_context(uid):
        assert get_timing_conflicts() == []   # need a conflicting pair, not just one


def test_isolation_and_api(app):
    c_a, uid_a = _uid(app, "tc5@medeasy.test")
    c_b, uid_b = _uid(app, "tc6@medeasy.test")
    _med(c_a, "A", ["07:00"], "empty_stomach")
    _med(c_a, "B", ["07:00"], "with_food")
    assert len(c_a.get("/api/medicines/timing-conflicts").get_json()["conflicts"]) == 1
    assert c_b.get("/api/medicines/timing-conflicts").get_json()["conflicts"] == []
