"""Derived health calculators — BMI, BSA, MAP. Honest formulas, None when unknown."""
import math
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.calculators import get_health_calculators
from db.food import update_profile
from db.health import log_vital

PW = "calc-pw-12345"


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


def _get(items, key):
    return next((i for i in items if i["key"] == key), None)


def test_nothing_without_profile(app):
    _, uid = _uid(app, "calc1@medeasy.test")
    with user_context(uid):
        d = get_health_calculators()
    assert d["has_data"] is False and _get(d["calculators"], "bmi") is None
    assert any("height and weight" in m for m in d["missing"])


def test_bmi_and_bsa(app):
    _, uid = _uid(app, "calc2@medeasy.test")
    with user_context(uid):
        update_profile({"weight_kg": 70, "height_cm": 175})
        d = get_health_calculators()
        bmi = _get(d["calculators"], "bmi")
        bsa = _get(d["calculators"], "bsa")
    assert bmi["value"] == round(70 / (1.75 ** 2), 1) == 22.9
    assert bmi["category"] == "Normal"
    assert bsa["value"] == round(math.sqrt(175 * 70 / 3600), 2)


def test_asia_pacific_category_differs(app):
    _, uid = _uid(app, "calc3@medeasy.test")
    with user_context(uid):
        update_profile({"weight_kg": 74, "height_cm": 170})   # BMI ~25.6
        bmi = _get(get_health_calculators()["calculators"], "bmi")
    assert bmi["category"] == "Overweight"
    assert bmi["asia_category"] == "Overweight"   # >=23 under Asia-Pacific too


def test_map_from_bp(app):
    _, uid = _uid(app, "calc4@medeasy.test")
    with user_context(uid):
        update_profile({"weight_kg": 70, "height_cm": 175})
        log_vital({"type": "blood_pressure", "value1": 120, "value2": 80})
        m = _get(get_health_calculators()["calculators"], "map")
    assert m["value"] == round(80 + (120 - 80) / 3)   # 93


def test_map_absent_without_bp(app):
    _, uid = _uid(app, "calc5@medeasy.test")
    with user_context(uid):
        update_profile({"weight_kg": 70, "height_cm": 175})
        d = get_health_calculators()
    assert _get(d["calculators"], "map") is None
    assert any("blood-pressure" in m for m in d["missing"])


def test_api(app):
    c, uid = _uid(app, "calc6@medeasy.test")
    with user_context(uid):
        update_profile({"weight_kg": 60, "height_cm": 160})
    body = c.get("/api/health/calculators").get_json()
    assert body["has_data"] is True
    assert _get(body["calculators"], "bmi")["unit"] == "kg/m²"
