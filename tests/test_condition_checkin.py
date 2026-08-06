"""Condition-tailored daily check-in (diabetes fasting/post-meal; BP)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import get_condition_checkin, set_condition_focus, get_condition_focus, log_vital

PW = "cci-pw-12345"


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


def test_no_focus_by_default(app):
    _, uid = _uid(app, "cci1@medeasy.test")
    with user_context(uid):
        d = get_condition_checkin()
    assert d["focus"] is None and d["prompts"] == []
    assert any(o["key"] == "diabetes" for o in d["options"])


def test_focus_set_and_clamped(app):
    _, uid = _uid(app, "cci2@medeasy.test")
    with user_context(uid):
        assert set_condition_focus("diabetes") == "diabetes"
        assert get_condition_focus() == "diabetes"
        assert set_condition_focus("nonsense") is None   # invalid → cleared
        assert get_condition_focus() is None


def test_diabetes_prompts_track_todays_logs(app):
    _, uid = _uid(app, "cci3@medeasy.test")
    with user_context(uid):
        set_condition_focus("diabetes")
        d = get_condition_checkin()
        keys = {p["key"]: p["done"] for p in d["prompts"]}
        assert keys == {"sugar_fasting": False, "sugar_post": False}
        # log a fasting sugar today
        log_vital({"type": "blood_sugar", "value1": 95, "context": "fasting"})
        d2 = get_condition_checkin()
        done = {p["key"]: p["done"] for p in d2["prompts"]}
        assert done["sugar_fasting"] is True and done["sugar_post"] is False
        assert d2["all_done"] is False


def test_hypertension_single_bp_prompt(app):
    _, uid = _uid(app, "cci4@medeasy.test")
    with user_context(uid):
        set_condition_focus("hypertension")
        assert get_condition_checkin()["prompts"][0]["done"] is False
        log_vital({"type": "blood_pressure", "value1": 120, "value2": 80})
        d = get_condition_checkin()
        assert d["prompts"][0]["done"] is True and d["all_done"] is True


def test_api(app):
    c, uid = _uid(app, "cci5@medeasy.test")
    assert c.post("/api/condition-focus", json={"focus": "diabetes"}).get_json()["focus"] == "diabetes"
    body = c.get("/api/condition-checkin").get_json()
    assert body["focus"] == "diabetes" and len(body["prompts"]) == 2
