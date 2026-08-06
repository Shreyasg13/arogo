"""Health-profile completeness — % filled + which fields are still missing."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.insights import get_profile_completeness
from db.food import update_profile
from db.health import save_emergency_info

PW = "pc-pw-12345"


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


def _keys(items):
    return {it["key"]: it["done"] for it in items}


def test_mostly_empty(app):
    _, uid = _uid(app, "pc1@medeasy.test")
    with user_context(uid):
        d = get_profile_completeness()
    assert d["pct"] < 100 and d["complete"] is False
    assert any(m["key"] == "blood" for m in d["missing"])


def test_filling_raises_pct(app):
    _, uid = _uid(app, "pc2@medeasy.test")
    with user_context(uid):
        before = get_profile_completeness()["pct"]
        update_profile({"name": "Asha", "age": 34, "gender": "female",
                        "height_cm": 165, "weight_kg": 60})
        after = get_profile_completeness()
    assert after["pct"] > before
    k = _keys(after["items"])
    assert k["weight"] and k["height"] and k["age"] and not k["blood"]


def test_full_profile(app):
    _, uid = _uid(app, "pc3@medeasy.test")
    with user_context(uid):
        update_profile({"name": "Ravi", "age": 40, "gender": "male",
                        "height_cm": 175, "weight_kg": 72})
        save_emergency_info({"blood_type": "O+", "conditions": "Hypertension",
                             "allergies": "Penicillin", "contact1_name": "Sita",
                             "contact1_phone": "9876500000"})
        d = get_profile_completeness()
    assert d["pct"] == 100 and d["complete"] is True and d["missing"] == []


def test_api(app):
    c, uid = _uid(app, "pc4@medeasy.test")
    body = c.get("/api/profile/completeness").get_json()
    assert "pct" in body and "missing" in body and body["total"] == 9
