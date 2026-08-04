"""Mood triggers on journal entries — tag what's driving a feeling, then get an
honest (non-causal) read of which triggers show up most on low-mood days."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context
from db.wellness import (save_thought, update_thought, get_thoughts,
                         get_trigger_patterns, clean_triggers)

PW = "trig-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    from db.core import execute
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def test_clean_triggers_filters_to_vocabulary():
    assert clean_triggers(["study", "STUDY", "work", "banana", ""]) == ["study", "work"]
    assert clean_triggers("sleep") == ["sleep"]
    assert clean_triggers(None) == []


def test_save_and_read_triggers(app):
    _, uid = _uid(app, "trig1@medeasy.test")
    with user_context(uid):
        t = save_thought("rough day", "stressed", "2026-08-01", triggers=["study", "sleep"])
        assert t["triggers"] == ["study", "sleep"]
        got = get_thoughts("2026-08-01")
    assert got[0]["triggers"] == ["study", "sleep"]


def test_triggers_optional_defaults_empty(app):
    _, uid = _uid(app, "trig2@medeasy.test")
    with user_context(uid):
        t = save_thought("just a note", "neutral", "2026-08-01")
    assert t["triggers"] == []


def test_update_replaces_triggers(app):
    _, uid = _uid(app, "trig3@medeasy.test")
    with user_context(uid):
        t = save_thought("x", "sad", "2026-08-01", triggers=["money"])
        t2 = update_thought(t["id"], "x", "sad", triggers=["family", "future"])
    assert t2["triggers"] == ["family", "future"]


def test_patterns_needs_min_count(app):
    _, uid = _uid(app, "trig4@medeasy.test")
    with user_context(uid):
        # 'study' twice — below min_count of 3 → not surfaced
        save_thought("a", "stressed", "2026-08-01", triggers=["study"])
        save_thought("b", "sad", "2026-08-01", triggers=["study"])
        p = get_trigger_patterns(days=3650, min_count=3)
    assert p["has_data"] is False


def test_patterns_ranks_low_mood_triggers(app):
    _, uid = _uid(app, "trig5@medeasy.test")
    with user_context(uid):
        for _ in range(3):
            save_thought("ugh", "anxious", "2026-08-01", triggers=["study"])
        for _ in range(3):
            save_thought("fine", "happy", "2026-08-01", triggers=["friends"])
        p = get_trigger_patterns(days=3650, min_count=3)
    assert p["has_data"] is True
    top = p["triggers"][0]
    assert top["key"] == "study"        # 3 low vs friends' 0 low
    assert top["low"] == 3 and top["total"] == 3


def test_api_round_trip(app):
    c, uid = _uid(app, "trig6@medeasy.test")
    r = c.post("/api/thoughts", json={"content": "test", "mood": "stressed",
                                      "date_key": "2026-08-01", "triggers": ["work", "sleep"]})
    assert r.status_code == 200
    assert r.get_json()["thought"]["triggers"] == ["work", "sleep"]
    # bogus trigger dropped, not error
    r2 = c.post("/api/thoughts", json={"content": "t2", "mood": "ok",
                                       "date_key": "2026-08-01", "triggers": ["nope"]})
    assert r2.status_code == 200 and r2.get_json()["thought"]["triggers"] == []
    assert c.get("/api/thoughts/patterns").status_code == 200
