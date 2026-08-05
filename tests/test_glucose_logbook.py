"""Blood-glucose logbook — meal-context tags on sugar readings, grouped stats."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import log_vital, get_glucose_logbook
from db.vital_targets import set_target

PW = "gl-pw-123456"


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


def test_context_stored_for_glucose(app):
    _, uid = _uid(app, "gl1@medeasy.test")
    with user_context(uid):
        v = log_vital({"type": "blood_sugar", "value1": 95, "context": "fasting"})
        assert v["context"] == "fasting"


def test_context_ignored_for_non_glucose(app):
    _, uid = _uid(app, "gl2@medeasy.test")
    with user_context(uid):
        v = log_vital({"type": "blood_pressure", "value1": 120, "value2": 80, "context": "fasting"})
        assert (v.get("context") or "") == ""       # a BP reading carries no meal context


def test_bad_context_becomes_random_in_logbook(app):
    _, uid = _uid(app, "gl3@medeasy.test")
    with user_context(uid):
        v = log_vital({"type": "blood_sugar", "value1": 110, "context": "nonsense"})
        assert (v.get("context") or "") == ""       # rejected tag stored empty
        book = get_glucose_logbook()
        assert book["readings"][0]["context"] == "random"   # surfaces as 'random'


def test_grouping_and_stats(app):
    _, uid = _uid(app, "gl4@medeasy.test")
    with user_context(uid):
        log_vital({"type": "blood_sugar", "value1": 90, "context": "fasting"})
        log_vital({"type": "blood_sugar", "value1": 100, "context": "fasting"})
        log_vital({"type": "blood_sugar", "value1": 160, "context": "post_meal"})
        book = get_glucose_logbook()
        by_ctx = {g["context"]: g for g in book["summary"]}
        assert by_ctx["fasting"]["count"] == 2
        assert by_ctx["fasting"]["avg"] == 95.0
        assert by_ctx["fasting"]["min"] == 90 and by_ctx["fasting"]["max"] == 100
        assert by_ctx["post_meal"]["count"] == 1
        assert by_ctx["post_meal"]["avg"] == 160.0


def test_flag_against_target(app):
    _, uid = _uid(app, "gl5@medeasy.test")
    with user_context(uid):
        set_target("blood_sugar", 80, 110)
        log_vital({"type": "blood_sugar", "value1": 150, "context": "post_meal"})
        log_vital({"type": "blood_sugar", "value1": 95, "context": "fasting"})
        book = get_glucose_logbook()
        flags = {r["value"]: r["flag"] for r in book["readings"]}
        assert flags[150] == "above"
        assert flags[95] == "in"
        post = next(g for g in book["summary"] if g["context"] == "post_meal")
        assert post["high"] == 1


def test_no_target_no_flag(app):
    _, uid = _uid(app, "gl6@medeasy.test")
    with user_context(uid):
        log_vital({"type": "blood_sugar", "value1": 300, "context": "random"})
        book = get_glucose_logbook()
        assert book["readings"][0]["flag"] is None      # no target set → no flag


def test_isolation(app):
    _, uid_a = _uid(app, "gl7@medeasy.test")
    _, uid_b = _uid(app, "gl8@medeasy.test")
    with user_context(uid_a):
        log_vital({"type": "blood_sugar", "value1": 88, "context": "fasting"})
    with user_context(uid_b):
        book = get_glucose_logbook()
        assert book["has_data"] is False and book["readings"] == []


def test_api_round_trip(app):
    c, uid = _uid(app, "gl9@medeasy.test")
    assert c.post("/api/vitals", json={"type": "blood_sugar", "value1": 105, "context": "pre_meal"}).status_code == 200
    book = c.get("/api/glucose/logbook").get_json()
    assert book["has_data"] is True
    assert book["readings"][0]["context"] == "pre_meal"
