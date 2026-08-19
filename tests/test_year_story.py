"""Year-in-health story — honest recap + a share-safe subset."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db.year_story import get_year_story, story_public_safe

PW = "story-pw-12345"


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


def _days_ago(n):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=n)).isoformat()


def test_empty_story_is_honest(app):
    _, uid = _uid(app, "story1@medeasy.test")
    with user_context(uid):
        s = get_year_story(365)
    assert s["started"] is False
    assert s["active_days"] == 0 and s["doses_taken"] == 0
    assert s["highlights"] == []                      # nothing invented


def test_counts_and_active_days(app):
    _, uid = _uid(app, "story2@medeasy.test")
    with user_context(uid):
        # 3 vitals across 2 distinct days, 1 workout, 1 taken dose
        execute("INSERT INTO vitals (id,date_key,type,value1,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), _days_ago(10), "blood_pressure", 120, now_iso(), uid), commit=True)
        execute("INSERT INTO vitals (id,date_key,type,value1,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), _days_ago(10), "heart_rate", 70, now_iso(), uid), commit=True)
        execute("INSERT INTO vitals (id,date_key,type,value1,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), _days_ago(5), "blood_sugar", 100, now_iso(), uid), commit=True)
        execute("INSERT INTO fitness_activities (id,type,date,created_at,user_id) VALUES (?,?,?,?,?)",
                (new_id(), "run", _days_ago(7), now_iso(), uid), commit=True)
        execute("INSERT INTO dose_logs (id,medicine_id,date_key,time_key,taken,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), "m1", _days_ago(3), "09:00", 1, uid), commit=True)
        s = get_year_story(365)
    assert s["counts"]["vitals"] == 3
    assert s["counts"]["workouts"] == 1
    assert s["doses_taken"] == 1
    assert s["active_days"] == 4                       # 3 vital-days(2)+workout(1)+dose(1) distinct = 4
    assert s["started"] is True
    assert any("vitals recorded" in h["text"] for h in s["highlights"])


def test_window_excludes_older_data(app):
    _, uid = _uid(app, "story3@medeasy.test")
    with user_context(uid):
        execute("INSERT INTO vitals (id,date_key,type,value1,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), _days_ago(400), "blood_pressure", 120, now_iso(), uid), commit=True)  # too old
        execute("INSERT INTO vitals (id,date_key,type,value1,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), _days_ago(20), "blood_pressure", 118, now_iso(), uid), commit=True)
        s90 = get_year_story(90)
        s365 = get_year_story(365)
    assert s90["counts"]["vitals"] == 1               # 20-day one only
    assert s365["counts"]["vitals"] == 1              # 400-day one is outside a year too


# ── share-safe subset ────────────────────────────────────────────────────────

def test_public_safe_strips_health_values(app):
    _, uid = _uid(app, "story4@medeasy.test")
    with user_context(uid):
        # a weight change + a symptom — both PRIVATE, must not appear publicly
        execute("INSERT INTO body_metrics (id,date_key,weight_kg,created_at,user_id) VALUES (?,?,?,?,?)",
                (new_id(), _days_ago(60), 80, now_iso(), uid), commit=True)
        execute("INSERT INTO body_metrics (id,date_key,weight_kg,created_at,user_id) VALUES (?,?,?,?,?)",
                (new_id(), _days_ago(5), 76, now_iso(), uid), commit=True)
        execute("INSERT INTO symptoms (id,name,severity,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), "Migraine", 6, _days_ago(9), now_iso(), uid), commit=True)
        full = get_year_story(365)
        safe = story_public_safe(full)
    # the full (own) story keeps private highlights
    assert full["weight_change"] is not None
    assert any("Weight" in h["text"] for h in full["highlights"])
    assert full["top_symptom"]["name"] == "Migraine"
    # the shareable subset drops them entirely
    assert "weight_change" not in safe and "top_symptom" not in safe
    assert "symptoms" not in safe["counts"]
    joined = " ".join(h["text"] for h in safe["highlights"])
    assert "Weight" not in joined and "Migraine" not in joined
    assert all(h.get("public") for h in safe["highlights"])


def test_route(app):
    c, _ = _uid(app, "story5@medeasy.test")
    body = c.get("/api/year-story?days=180").get_json()
    assert body["period"]["days"] == 180 and "highlights" in body


def test_route_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/year-story").status_code in (401, 403)


def test_prompt_decision_year_end_and_anniversary():
    from db.year_story import _prompt_decision
    # empty story → never prompt, even at year-end
    assert _prompt_decision("2026-12-20", "2025-01-01", False)["show"] is False
    # mid-December → calendar prompt
    d = _prompt_decision("2026-12-20", "2026-11-01", True)
    assert d["show"] and d["reason"] == "calendar" and d["year"] == 2026
    # early December (before the 15th) → no calendar prompt
    assert _prompt_decision("2026-12-05", "2026-11-01", True)["show"] is False
    # ~1 year after signup (Aug) → anniversary prompt
    d = _prompt_decision("2026-08-19", "2025-08-16", True)
    assert d["show"] and d["reason"] == "anniversary" and d["years"] == 1
    # 4 months in, not December → no prompt
    assert _prompt_decision("2026-08-19", "2026-04-19", True)["show"] is False


def test_prompt_route(app):
    c, _ = _uid(app, "storyprompt@medeasy.test")
    body = c.get("/api/year-story/prompt").get_json()
    assert "show" in body            # new account, no data → show False
    assert body["show"] is False


def test_share_story_scope_is_safe(app):
    """A shared 'story' link must carry the safe subset only — no health values."""
    from db.shares import create_snapshot, resolve_snapshot, compile_snapshot
    _, uid = _uid(app, "story7@medeasy.test")
    with user_context(uid):
        execute("INSERT INTO body_metrics (id,date_key,weight_kg,created_at,user_id) VALUES (?,?,?,?,?)",
                (new_id(), _days_ago(30), 90, now_iso(), uid), commit=True)
        execute("INSERT INTO symptoms (id,name,severity,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
                (new_id(), "Backpain", 5, _days_ago(4), now_iso(), uid), commit=True)
        snap = create_snapshot(label="my year", days_valid=7, scope="story")
    resolved = resolve_snapshot(snap["token"])
    d = compile_snapshot(resolved["user_id"], resolved["id"], resolved["scope"])
    assert d["scope"] == "story"
    assert "vitals" not in d and "medications" not in d      # summary-scope fields absent
    st = d["story"]
    assert "weight_change" not in st and "top_symptom" not in st
    assert "symptoms" not in st["counts"]
    assert all(h.get("public") for h in st["highlights"])
