"""Weekly review ritual — compose existing recaps + save a reflection."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today
from db.weekly_review import get_weekly_review, save_weekly_review, _week_start

PW = "wrev-pw-12345"


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


def test_week_start_is_monday():
    ws = _week_start(user_today())
    assert dt.date.fromisoformat(ws).weekday() == 0


def test_shape_composes_recaps(app):
    _, uid = _uid(app, "wrev1@medeasy.test")
    with user_context(uid):
        d = get_weekly_review()
    assert set(["week_start", "review", "deltas", "gaps", "saved", "history"]).issubset(d)
    assert d["saved"] is None and d["history"] == []
    # review is the reused generate_health_review payload
    assert "wins" in d["review"] and "adherence" in d["review"]


def test_save_and_reload_reflection(app):
    _, uid = _uid(app, "wrev2@medeasy.test")
    with user_context(uid):
        save_weekly_review("Walked every morning", "Log BP daily")
        d = get_weekly_review()
    assert d["saved"]["wins"] == "Walked every morning"
    assert d["saved"]["focus"] == "Log BP daily"


def test_save_is_upsert_one_row_per_week(app):
    _, uid = _uid(app, "wrev3@medeasy.test")
    with user_context(uid):
        save_weekly_review("first", "a")
        save_weekly_review("second", "b")   # same week → overwrite, not duplicate
        n = execute("SELECT COUNT(*) c FROM weekly_reviews WHERE user_id=?", (uid,), fetchone=True)["c"]
        d = get_weekly_review()
    assert n == 1
    assert d["saved"]["wins"] == "second"


def test_history_excludes_current_week(app):
    _, uid = _uid(app, "wrev4@medeasy.test")
    ws = _week_start(user_today())
    prev = (dt.date.fromisoformat(ws) - dt.timedelta(days=7)).isoformat()
    with user_context(uid):
        # seed a prior week's reflection directly
        from db.core import new_id, now_iso
        execute("""INSERT INTO weekly_reviews (id,week_start,wins,focus,created_at,updated_at,user_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), prev, "last week win", "last focus", now_iso(), now_iso(), uid), commit=True)
        save_weekly_review("this week", "this focus")
        d = get_weekly_review()
    assert d["saved"]["wins"] == "this week"
    assert [h["week_start"] for h in d["history"]] == [prev]


def test_isolation(app):
    _, a = _uid(app, "wrev5a@medeasy.test")
    _, b = _uid(app, "wrev5b@medeasy.test")
    with user_context(a):
        save_weekly_review("A wins", "A focus")
    with user_context(b):
        d = get_weekly_review()
    assert d["saved"] is None   # B never sees A's reflection


def test_routes(app):
    c, _ = _uid(app, "wrev6@medeasy.test")
    assert c.get("/api/weekly-review").status_code == 200
    r = c.post("/api/weekly-review", json={"wins": "x", "focus": "y"}).get_json()
    assert r["success"] and r["saved"]["focus"] == "y"
    # persisted
    assert c.get("/api/weekly-review").get_json()["saved"]["wins"] == "x"


def test_route_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/weekly-review").status_code in (401, 403)
