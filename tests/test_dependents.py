"""Dependents / family profiles — CRUD + records, with the ownership boundary
(you can't touch or attach records to someone else's dependent)."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.dependents import (create_dependent, add_record, get_records, list_dependents,
                           delete_dependent, update_dependent)

PW = "dep-pw-12345"


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


def test_create_with_age_and_counts(app):
    c, uid = _uid(app, "dep1@medeasy.test")
    with user_context(uid):
        bd = (dt.date.today().replace(year=dt.date.today().year - 7)).isoformat()
        dep = create_dependent("Aarav", "child", bd)
        add_record(dep["id"], "vaccine", "MR", "Dose 1", "2026-01-10")
        add_record(dep["id"], "medicine", "Paracetamol syrup")
        deps = list_dependents()
    d = deps[0]
    assert d["name"] == "Aarav" and d["relationship"] == "child" and d["age"] == 7
    assert d["counts"] == {"vaccine": 1, "medicine": 1}


def test_records_grouped_by_kind(app):
    c, uid = _uid(app, "dep2@medeasy.test")
    with user_context(uid):
        dep = create_dependent("Ma", "parent")
        add_record(dep["id"], "medicine", "Amlodipine 5mg", "morning")
        add_record(dep["id"], "note", "Allergic to penicillin")
        rec = get_records(dep["id"])
    assert rec["dependent"]["name"] == "Ma"
    assert len(rec["records"]["medicine"]) == 1 and len(rec["records"]["note"]) == 1
    assert rec["total"] == 2


def test_bad_input_rejected(app):
    _, uid = _uid(app, "dep3@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_dependent("")                     # no name
        dep = create_dependent("Kid")
        with pytest.raises(ValueError):
            add_record(dep["id"], "invalid_kind", "x")
        with pytest.raises(ValueError):
            add_record(dep["id"], "note", "")        # no label


def test_cannot_touch_another_users_dependent(app):
    ca, ua = _uid(app, "dep-a@medeasy.test")
    cb, ub = _uid(app, "dep-b@medeasy.test")
    with user_context(ua):
        dep = create_dependent("A's child", "child")
    # B must not be able to add a record, edit, or read A's dependent.
    with user_context(ub):
        with pytest.raises(ValueError):
            add_record(dep["id"], "note", "hijack")
        with pytest.raises(ValueError):
            update_dependent(dep["id"], {"name": "hijacked"})
        with pytest.raises(ValueError):
            get_records(dep["id"])
        assert list_dependents() == []               # B sees none
    # A's dependent is intact.
    with user_context(ua):
        assert get_records(dep["id"])["dependent"]["name"] == "A's child"


def test_delete_cascades_records(app):
    c, uid = _uid(app, "dep4@medeasy.test")
    with user_context(uid):
        dep = create_dependent("Temp")
        add_record(dep["id"], "vaccine", "BCG")
        delete_dependent(dep["id"])
        assert list_dependents() == []
    # records gone too
    left = execute("SELECT COUNT(*) c FROM dependent_records WHERE dependent_id=?",
                   (dep["id"],), fetchone=True)["c"]
    assert left == 0


def test_api_round_trip(app):
    c, uid = _uid(app, "dep5@medeasy.test")
    dep = c.post("/api/dependents", json={"name": "Dadi", "relationship": "grandparent"}).get_json()["dependent"]
    r = c.post(f"/api/dependents/{dep['id']}/records",
               json={"kind": "medicine", "label": "Metformin", "detail": "twice daily"})
    assert r.status_code == 200
    recs = c.get(f"/api/dependents/{dep['id']}/records").get_json()
    assert recs["total"] == 1
    assert "child" in c.get("/api/dependents/meta").get_json()["relationships"]
    # reading a foreign/nonexistent dependent's records → 404
    assert c.get("/api/dependents/nope/records").status_code == 404
