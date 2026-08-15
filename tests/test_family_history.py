"""N3 family medical history — plain, user-stated facts about relatives'
conditions, for the question every new doctor asks. Facts only, never scored or
interpreted; every entry user-scoped."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "famhx-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def test_add_and_list(app):
    c = _reg(app, "fh1@medeasy.test")
    c.post("/api/family-history", json={"relation": "father", "condition": "Type 2 diabetes", "age_at_onset": 52})
    c.post("/api/family-history", json={"relation": "mother", "condition": "Hypertension"})
    entries = c.get("/api/family-history").get_json()["entries"]
    assert len(entries) == 2
    dad = next(e for e in entries if e["relation"] == "father")
    assert dad["condition"] == "Type 2 diabetes" and dad["age_at_onset"] == 52


def test_condition_required(app):
    c = _reg(app, "fh2@medeasy.test")
    assert c.post("/api/family-history", json={"relation": "mother", "condition": ""}).status_code == 400


def test_unknown_relation_becomes_other(app):
    c = _reg(app, "fh3@medeasy.test")
    e = c.post("/api/family-history", json={"relation": "second cousin", "condition": "Asthma"}).get_json()["entry"]
    assert e["relation"] == "other"


def test_blank_age_stays_null_not_zero(app):
    c = _reg(app, "fh4@medeasy.test")
    # An unstated onset age must be null, never a fabricated 0.
    e = c.post("/api/family-history", json={"relation": "sister", "condition": "Migraine", "age_at_onset": ""}).get_json()["entry"]
    assert e["age_at_onset"] is None


def test_delete(app):
    c = _reg(app, "fh5@medeasy.test")
    e = c.post("/api/family-history", json={"relation": "brother", "condition": "Epilepsy"}).get_json()["entry"]
    c.delete(f"/api/family-history/{e['id']}")
    assert c.get("/api/family-history").get_json()["entries"] == []


def test_user_scoped(app):
    a = _reg(app, "fh6a@medeasy.test")
    b = _reg(app, "fh6b@medeasy.test")
    e = a.post("/api/family-history", json={"relation": "mother", "condition": "Private condition"}).get_json()["entry"]
    assert b.get("/api/family-history").get_json()["entries"] == []
    b.delete(f"/api/family-history/{e['id']}")          # no-op for A
    assert len(a.get("/api/family-history").get_json()["entries"]) == 1


def test_requires_auth(app):
    assert app.test_client().get("/api/family-history").status_code in (401, 403)
