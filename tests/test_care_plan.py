"""Shared care plan — user/caregiver/doctor-authored items, sanitized vocab,
per-user isolation."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.care_plan import create_item, update_item, list_plan, delete_item

PW = "care-pw-12345"


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


def test_create_and_list(app):
    _, uid = _uid(app, "careplan1@medeasy.test")
    with user_context(uid):
        create_item("Walk 30 min daily", "After dinner", "lifestyle", "me")
        create_item("Check BP weekly", owner="caregiver", category="monitoring")
        plan = list_plan()
    assert plan["summary"]["total"] == 2 and plan["summary"]["active"] == 2
    titles = [i["title"] for i in plan["items"]]
    assert "Walk 30 min daily" in titles and "Check BP weekly" in titles


def test_bad_category_and_owner_sanitized(app):
    _, uid = _uid(app, "careplan2@medeasy.test")
    with user_context(uid):
        it = create_item("Take meds", category="nonsense", owner="hacker")
    assert it["category"] == "other" and it["owner"] == "me"


def test_title_required(app):
    _, uid = _uid(app, "careplan3@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_item("   ")


def test_mark_done_and_summary(app):
    _, uid = _uid(app, "careplan4@medeasy.test")
    with user_context(uid):
        it = create_item("Book eye exam", category="appointment", owner="doctor")
        update_item(it["id"], {"status": "done"})
        plan = list_plan()
    assert plan["summary"]["done"] == 1 and plan["summary"]["active"] == 0
    # done items sort after active
    assert plan["items"][-1]["status"] == "done"


def test_review_date_validation(app):
    _, uid = _uid(app, "careplan5@medeasy.test")
    with user_context(uid):
        it = create_item("Review statin dose", review_date="not-a-date")
        assert it["review_date"] is None
        it2 = create_item("Renew prescription", review_date="2026-12-01")
        assert it2["review_date"] == "2026-12-01"


def test_isolation(app):
    _, uid_a = _uid(app, "careplan6@medeasy.test")
    _, uid_b = _uid(app, "careplan7@medeasy.test")
    with user_context(uid_a):
        create_item("Private plan item A")
    with user_context(uid_b):
        plan_b = list_plan()
    assert all(i["title"] != "Private plan item A" for i in plan_b["items"])


def test_api_round_trip(app):
    c, uid = _uid(app, "careplan8@medeasy.test")
    r = c.post("/api/care-plan", json={"title": "Low-salt diet", "category": "lifestyle", "owner": "me"})
    assert r.status_code == 200
    iid = r.get_json()["item"]["id"]
    assert c.get("/api/care-plan").get_json()["summary"]["total"] == 1
    assert c.patch(f"/api/care-plan/{iid}", json={"status": "done"}).get_json()["item"]["status"] == "done"
    assert c.delete(f"/api/care-plan/{iid}").get_json()["success"] is True
    assert c.post("/api/care-plan", json={"title": ""}).status_code == 400
