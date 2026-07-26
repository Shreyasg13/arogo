"""Tests for drug-name autocomplete.

The safety contract matters as much as the search: entries carry ONLY a name
and an identifier hint — no dosing, no interactions — so a test locks that down.
"""
import pytest

import auth as auth_module
from db.core import init_db
from app import create_app
import drug_data


def test_search_prefix_first():
    r = drug_data.search_drugs("para")
    assert any(d["name"] == "Paracetamol" for d in r)
    assert r[0]["name"].lower().startswith("para")   # prefix ranked ahead of substring


def test_search_matches_hint_for_brands():
    # brands whose generic is azithromycin should surface on that search
    r = drug_data.search_drugs("azithromycin")
    assert any(d["name"] in ("Azithral", "Azee") for d in r)


def test_empty_query_returns_nothing():
    assert drug_data.search_drugs("") == []
    assert drug_data.search_drugs("   ") == []


def test_limit_respected():
    assert len(drug_data.search_drugs("a", limit=5)) <= 5


def test_entries_carry_no_dosing_or_interaction_data():
    for d in drug_data.DRUGS:
        assert set(d.keys()) == {"name", "hint"}, f"unexpected fields on {d}"
        assert d["name"] and isinstance(d["name"], str)


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


def test_route_returns_matches(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "drug@medeasy.test", "password": "drug-pw-12345"})
    r = c.get("/api/medicines/drugs?q=dolo")
    assert r.status_code == 200
    assert any(x["name"] == "Dolo 650" for x in r.get_json()["drugs"])


def test_route_empty_query(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "drug2@medeasy.test", "password": "drug-pw-12345"})
    assert c.get("/api/medicines/drugs?q=").get_json()["drugs"] == []
