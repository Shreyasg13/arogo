"""K2 — estimated HbA1c from logged glucose. ADAG formula on the user's own
blood-sugar average, framed as an estimate. Needs enough readings."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.glucose_a1c import estimate_a1c, _MIN_READINGS

PW = "a1c-pw-1234567"


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


def _sugar(uid, mgdl, day="2026-08-01"):
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), day, "blood_sugar", mgdl, None, "mg/dL", f"{day}T09:00:00", uid), commit=True)


def test_needs_enough_readings(app):
    _, uid = _uid(app, "a1c1@medeasy.test")
    with user_context(uid):
        for _ in range(_MIN_READINGS - 1):
            _sugar(uid, 120)
        d = estimate_a1c()
    assert d["has_data"] is False


def test_adag_formula(app):
    _, uid = _uid(app, "a1c2@medeasy.test")
    with user_context(uid):
        for _ in range(_MIN_READINGS):
            _sugar(uid, 154)          # mean 154 → A1c = (154+46.7)/28.7 ≈ 7.0
        d = estimate_a1c()
    assert d["has_data"] is True
    assert d["avg_glucose"] == 154
    assert d["estimated_a1c"] == round((154 + 46.7) / 28.7, 1)   # ~7.0


def test_mmol_reading_is_converted(app):
    _, uid = _uid(app, "a1c3@medeasy.test")
    with user_context(uid):
        # A value under 40 is treated as mmol/L and ×18 to mg/dL (8.5 → 153).
        for _ in range(_MIN_READINGS):
            _sugar(uid, 8.5)
        d = estimate_a1c()
    assert d["avg_glucose"] == round(8.5 * 18)     # ~153, not a wild number from 8.5


def test_genuine_low_reading_not_misconverted(app):
    # A real hypo (38 mg/dL) among mg/dL readings must NOT be treated as mmol/L
    # and inflated x18 — the unit is decided from the whole series, not per reading.
    _, uid = _uid(app, "a1c5@medeasy.test")
    with user_context(uid):
        for _ in range(_MIN_READINGS - 1):
            _sugar(uid, 150)
        _sugar(uid, 38)                 # a genuine low, in mg/dL
        d = estimate_a1c()
    # Mean is ~139 (well above 40) → whole series read as mg/dL; the 38 stays 38.
    assert d["avg_glucose"] < 160       # not blown up by a 38*18=684 misconversion
    assert 6 <= d["estimated_a1c"] <= 7


def test_api(app):
    c, uid = _uid(app, "a1c4@medeasy.test")
    with user_context(uid):
        for _ in range(_MIN_READINGS):
            _sugar(uid, 130)
    body = c.get("/api/vitals/estimated-a1c").get_json()
    assert body["has_data"] is True and body["avg_glucose"] == 130
