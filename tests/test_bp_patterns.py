"""K4 — home-vs-clinic BP (white-coat); K5 — morning-vs-evening BP. Plain averages
of the user's own BP readings, split by context tag / time logged. Comparison only
appears when both groups have data."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.health import log_vital
from db.bp_patterns import get_bp_home_vs_clinic, get_bp_time_pattern

PW = "bpp-pw-1234567"


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


def _bp(uid, sys, dia, context="", logged_hour=9, day="2026-08-01"):
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,notes,context,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (new_id(), day, "blood_pressure", sys, dia, "mmHg", "", context,
             f"{day}T{logged_hour:02d}:00:00", uid), commit=True)


# ── K4 ──
def test_context_only_stored_for_valid_bp_tags(app):
    _, uid = _uid(app, "bpp1@medeasy.test")
    with user_context(uid):
        v = log_vital({"type": "blood_pressure", "value1": 120, "value2": 80, "context": "home"})
        assert v["context"] == "home"
        v2 = log_vital({"type": "blood_pressure", "value1": 120, "value2": 80, "context": "garden"})
        assert v2["context"] == ""      # invalid tag dropped


def test_home_vs_clinic_needs_both(app):
    _, uid = _uid(app, "bpp2@medeasy.test")
    with user_context(uid):
        _bp(uid, 120, 80, "home")
        d = get_bp_home_vs_clinic()
    assert d["has_data"] is False       # no clinic readings


def test_white_coat_gap(app):
    _, uid = _uid(app, "bpp3@medeasy.test")
    with user_context(uid):
        for _ in range(3): _bp(uid, 122, 80, "home")     # home ~122
        for _ in range(3): _bp(uid, 140, 88, "clinic")   # clinic ~140
        d = get_bp_home_vs_clinic()
    assert d["has_data"] is True
    assert d["home"]["systolic"] == 122 and d["clinic"]["systolic"] == 140
    assert d["systolic_gap"] == 18 and d["white_coat"] is True


# ── K5 ──
def test_morning_vs_evening_split(app):
    _, uid = _uid(app, "bpp4@medeasy.test")
    with user_context(uid):
        for _ in range(3): _bp(uid, 135, 85, logged_hour=7)    # morning
        for _ in range(3): _bp(uid, 125, 80, logged_hour=20)   # evening
        d = get_bp_time_pattern()
    assert d["has_data"] is True
    assert d["morning"]["systolic"] == 135 and d["evening"]["systolic"] == 125
    assert d["systolic_gap"] == 10          # morning higher


def test_time_pattern_needs_both_slots(app):
    _, uid = _uid(app, "bpp5@medeasy.test")
    with user_context(uid):
        _bp(uid, 130, 82, logged_hour=8)    # morning only
        d = get_bp_time_pattern()
    assert d["has_data"] is False


def test_api(app):
    c, uid = _uid(app, "bpp6@medeasy.test")
    with user_context(uid):
        _bp(uid, 120, 80, "home", logged_hour=7)
        _bp(uid, 138, 86, "clinic", logged_hour=20)
    hc = c.get("/api/vitals/bp-home-clinic").get_json()
    tp = c.get("/api/vitals/bp-time-pattern").get_json()
    assert hc["has_data"] is True and tp["has_data"] is True
