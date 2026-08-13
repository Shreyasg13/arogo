"""J3 — emergency action plans. User-authored titled, ordered steps for a
specific emergency. Arogo supplies only blank title scaffolds; every step is the
user's own. Owner-scoped CRUD."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.action_plans import (create_action_plan, update_action_plan,
                             list_action_plans, delete_action_plan, PLAN_SUGGESTIONS)

PW = "ap-pw-1234567"


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


def test_suggestions_carry_no_medical_steps(app):
    c, _ = _uid(app, "ap1@medeasy.test")
    body = c.get("/api/action-plans").get_json()
    assert body["plans"] == []
    assert set(body["suggestions"]) == set(PLAN_SUGGESTIONS)
    # Suggestions are titles only — plain strings, never step lists.
    assert all(isinstance(s, str) for s in body["suggestions"])


def test_create_requires_title(app):
    _, uid = _uid(app, "ap2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_action_plan({"title": "   ", "steps": ["do a thing"]})


def test_create_and_steps_cleaned(app):
    _, uid = _uid(app, "ap3@medeasy.test")
    with user_context(uid):
        p = create_action_plan({"title": "Anaphylaxis",
                                "steps": ["Use EpiPen", "  ", "Call 108", "x" * 500]})
        assert p["title"] == "Anaphylaxis"
        assert p["steps"][0] == "Use EpiPen" and p["steps"][1] == "Call 108"
        assert len(p["steps"]) == 3                 # blank dropped
        assert len(p["steps"][2]) == 300            # over-long step trimmed


def test_update_replaces_steps(app):
    _, uid = _uid(app, "ap4@medeasy.test")
    with user_context(uid):
        p = create_action_plan({"title": "Asthma", "steps": ["Blue inhaler x4"]})
        up = update_action_plan(p["id"], {"steps": ["Sit up", "Blue inhaler x4", "Call for help"]})
        assert up["steps"] == ["Sit up", "Blue inhaler x4", "Call for help"]
        assert up["title"] == "Asthma"              # unchanged when omitted


def test_owner_scoped(app):
    _, ouid = _uid(app, "ap5@medeasy.test")
    with user_context(ouid):
        p = create_action_plan({"title": "Seizure", "steps": ["Time it"]})
    _, other = _uid(app, "ap6@medeasy.test")
    with user_context(other):
        assert list_action_plans() == []           # can't see the owner's plan
        with pytest.raises(ValueError):
            update_action_plan(p["id"], {"title": "Hijacked"})
        delete_action_plan(p["id"])                 # no-op on a foreign plan
    with user_context(ouid):
        assert list_action_plans()[0]["title"] == "Seizure"   # untouched


def test_api_crud(app):
    c, uid = _uid(app, "ap7@medeasy.test")
    pid = c.post("/api/action-plans", json={"title": "Low sugar", "steps": ["15g glucose"]}).get_json()["plan"]["id"]
    assert c.put(f"/api/action-plans/{pid}", json={"steps": ["15g glucose", "recheck in 15 min"]}).status_code == 200
    plans = c.get("/api/action-plans").get_json()["plans"]
    assert plans[0]["steps"] == ["15g glucose", "recheck in 15 min"]
    assert c.delete(f"/api/action-plans/{pid}").status_code == 200
    assert c.get("/api/action-plans").get_json()["plans"] == []
