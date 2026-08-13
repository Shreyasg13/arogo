"""I7 — symptom body-map. Symptoms carry an optional body-region tag; the map
counts them per region. Region is validated against a fixed enum; everything is
the user's own logged data (no interpretation, no invented regions)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import log_symptom, get_symptoms_by_region, get_symptoms, BODY_REGIONS

PW = "sreg-pw-12345"


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


def test_region_stored_when_valid(app):
    _, uid = _uid(app, "sreg1@medeasy.test")
    with user_context(uid):
        s = log_symptom({"name": "Headache", "severity": 6, "region": "head"})
        assert s["region"] == "head"


def test_invalid_region_is_dropped_not_stored(app):
    _, uid = _uid(app, "sreg2@medeasy.test")
    with user_context(uid):
        s = log_symptom({"name": "Ache", "region": "left-earlobe"})   # not in enum
        assert s["region"] == ""
        s2 = log_symptom({"name": "Ache2"})                            # omitted entirely
        assert s2["region"] == ""


def test_by_region_counts_and_worst(app):
    _, uid = _uid(app, "sreg3@medeasy.test")
    with user_context(uid):
        log_symptom({"name": "Cramp", "severity": 4, "region": "abdomen"})
        log_symptom({"name": "Cramp", "severity": 8, "region": "abdomen"})
        log_symptom({"name": "Sore", "severity": 3, "region": "legs"})
        log_symptom({"name": "Nonlocal", "severity": 5})               # no region → excluded
        d = get_symptoms_by_region(days=90)
    assert d["has_data"] is True
    assert d["counts"]["abdomen"] == 2 and d["counts"]["legs"] == 1
    assert "general" not in d["counts"]        # the untagged one isn't counted anywhere
    assert d["worst"]["abdomen"] == 8
    assert d["total"] == 3
    assert list(d["regions"]) == list(BODY_REGIONS)   # full map always returned


def test_by_region_empty(app):
    _, uid = _uid(app, "sreg4@medeasy.test")
    with user_context(uid):
        log_symptom({"name": "Untagged"})      # no region
        d = get_symptoms_by_region()
    assert d["has_data"] is False and d["counts"] == {}


def test_region_flows_through_api_and_back(app):
    c, uid = _uid(app, "sreg5@medeasy.test")
    r = c.post("/api/symptoms", json={"name": "Rash", "severity": 5, "region": "skin"})
    assert r.get_json()["success"] is True
    # It reads back on the symptom list…
    with user_context(uid):
        got = [s for s in get_symptoms(14) if s["name"] == "Rash"][0]
    assert got["region"] == "skin"
    # …and in the body-region endpoint.
    body = c.get("/api/symptoms/by-region?days=90").get_json()
    assert body["counts"]["skin"] == 1
