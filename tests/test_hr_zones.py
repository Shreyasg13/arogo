"""Exercise heart-rate zones from age (Tanaka max-HR)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.calculators import get_hr_zones
from db.food import update_profile

PW = "hrz-pw-12345"


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


def test_no_age_no_zones(app):
    _, uid = _uid(app, "hrz1@medeasy.test")
    with user_context(uid):
        d = get_hr_zones()
    assert d["has_data"] is False and "age" in d["reason"]


def test_zones_from_age(app):
    _, uid = _uid(app, "hrz2@medeasy.test")
    with user_context(uid):
        update_profile({"age": 30})
        d = get_hr_zones()
    assert d["has_data"] is True
    assert d["max_hr"] == round(208 - 0.7 * 30) == 187
    zones = {z["key"]: z for z in d["zones"]}
    assert zones["fatburn"]["lo_bpm"] == round(187 * 0.6) and zones["fatburn"]["hi_bpm"] == round(187 * 0.7)
    assert zones["peak"]["hi_bpm"] == 187
    assert len(d["zones"]) == 5


def test_api(app):
    c, uid = _uid(app, "hrz3@medeasy.test")
    with user_context(uid):
        update_profile({"age": 45})
    body = c.get("/api/health/hr-zones").get_json()
    assert body["has_data"] is True and body["max_hr"] == round(208 - 0.7 * 45)
