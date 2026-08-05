"""Structured allergy log — severity ordering, Health ID integration, isolation."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.allergies import (create_allergy, update_allergy, delete_allergy,
                          list_allergies, allergy_summary)
from db.health_id import get_health_id

PW = "alg-pw-123456"


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


def test_create_and_severity_order(app):
    _, uid = _uid(app, "alg1@medeasy.test")
    with user_context(uid):
        create_allergy({"allergen": "Dust", "severity": "mild"})
        create_allergy({"allergen": "Penicillin", "severity": "severe", "reaction": "rash"})
        create_allergy({"allergen": "Pollen", "severity": "moderate"})
        rows = list_allergies()
    assert [r["allergen"] for r in rows] == ["Penicillin", "Pollen", "Dust"]   # severe → mild


def test_allergen_required(app):
    _, uid = _uid(app, "alg2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_allergy({"reaction": "rash"})


def test_bad_severity_defaults_moderate(app):
    _, uid = _uid(app, "alg3@medeasy.test")
    with user_context(uid):
        a = create_allergy({"allergen": "X", "severity": "catastrophic"})
    assert a["severity"] == "moderate"


def test_summary_flags_severe_only(app):
    _, uid = _uid(app, "alg4@medeasy.test")
    with user_context(uid):
        create_allergy({"allergen": "Penicillin", "severity": "severe"})
        create_allergy({"allergen": "Peanuts", "severity": "moderate"})
        s = allergy_summary()
    assert s == "Penicillin (severe), Peanuts"


def test_feeds_health_id_card(app):
    _, uid = _uid(app, "alg5@medeasy.test")
    with user_context(uid):
        create_allergy({"allergen": "Sulfa", "severity": "severe", "reaction": "hives"})
        card = get_health_id()
    assert card["allergy_list"] == [{"allergen": "Sulfa", "reaction": "hives", "severity": "severe"}]


def test_update_and_delete(app):
    _, uid = _uid(app, "alg6@medeasy.test")
    with user_context(uid):
        a = create_allergy({"allergen": "Latex", "severity": "mild"})
        upd = update_allergy(a["id"], {"severity": "severe", "reaction": "swelling"})
        assert upd["severity"] == "severe" and upd["reaction"] == "swelling"
        delete_allergy(a["id"])
        assert list_allergies() == []


def test_isolation(app):
    _, uid_a = _uid(app, "alg7@medeasy.test")
    _, uid_b = _uid(app, "alg8@medeasy.test")
    with user_context(uid_a):
        create_allergy({"allergen": "SecretAllergen"})
    with user_context(uid_b):
        assert list_allergies() == []


def test_api_round_trip(app):
    c, uid = _uid(app, "alg9@medeasy.test")
    r = c.post("/api/allergies", json={"allergen": "Aspirin", "severity": "moderate"})
    assert r.status_code == 200
    aid = r.get_json()["allergy"]["id"]
    assert c.get("/api/allergies").get_json()["allergies"][0]["allergen"] == "Aspirin"
    assert c.patch(f"/api/allergies/{aid}", json={"severity": "severe"}).get_json()["allergy"]["severity"] == "severe"
    assert c.delete(f"/api/allergies/{aid}").get_json()["success"] is True
    assert c.post("/api/allergies", json={"allergen": ""}).status_code == 400
