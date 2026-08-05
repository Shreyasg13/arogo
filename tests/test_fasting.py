"""Intermittent-fasting tracker — durations measured from the user's own clock,
one active fast at a time, honest stats."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.fasting import start_fast, end_fast, get_active, list_fasts, delete_fast

PW = "fast-pw-12345"


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


def _ago(hours):
    return (_dt.datetime.now() - _dt.timedelta(hours=hours)).isoformat()


def test_start_and_active(app):
    _, uid = _uid(app, "fast1@medeasy.test")
    with user_context(uid):
        f = start_fast(16, start_at=_ago(10))    # 10h into a 16h fast
        assert f["status"] == "active"
        a = get_active()
    assert a is not None
    assert a["elapsed_hours"] == pytest.approx(10, abs=0.1)
    assert a["remaining_hours"] == pytest.approx(6, abs=0.1)
    assert a["reached_target"] is False


def test_only_one_active(app):
    _, uid = _uid(app, "fast2@medeasy.test")
    with user_context(uid):
        start_fast(16)
        with pytest.raises(ValueError):
            start_fast(18)


def test_end_computes_duration(app):
    _, uid = _uid(app, "fast3@medeasy.test")
    with user_context(uid):
        start_fast(16, start_at=_ago(17))
        done = end_fast()                         # ends now → ~17h
        assert done["status"] == "completed"
        assert done["duration_hours"] == pytest.approx(17, abs=0.1)
        assert done["reached_target"] is True     # 17 >= 16
        assert get_active() is None               # no active fast after ending


def test_end_bad_time_falls_back_to_now(app):
    _, uid = _uid(app, "fast4@medeasy.test")
    with user_context(uid):
        start_fast(16, start_at=_ago(5))
        # An end before the start is nonsense → falls back to now (~5h duration).
        done = end_fast(end_at=_ago(40))
        assert done["duration_hours"] == pytest.approx(5, abs=0.1)


def test_stats_and_history(app):
    _, uid = _uid(app, "fast5@medeasy.test")
    with user_context(uid):
        start_fast(16, start_at=_ago(30)); end_fast(end_at=_ago(16))   # 14h
        start_fast(16, start_at=_ago(10)); end_fast(end_at=_ago(0))    # 10h
        out = list_fasts()
    assert out["stats"]["completed"] == 2
    assert out["stats"]["avg_hours"] == pytest.approx(12.0, abs=0.1)
    assert out["stats"]["longest_hours"] == pytest.approx(14.0, abs=0.1)
    assert len(out["history"]) == 2


def test_future_start_ignored(app):
    _, uid = _uid(app, "fast6@medeasy.test")
    with user_context(uid):
        f = start_fast(16, start_at=(_dt.datetime.now() + _dt.timedelta(hours=3)).isoformat())
        # A future start is rejected → starts now, so elapsed ~0.
        assert f["elapsed_hours"] == pytest.approx(0, abs=0.1)


def test_tz_aware_input_does_not_crash(app):
    # A mobile client may send an offset-bearing ISO string; it must not 500.
    c, uid = _uid(app, "fast8@medeasy.test")
    r = c.post("/api/fasting/start", json={"target_hours": 16,
                                           "start_at": "2026-08-04T10:00:00+05:30"})
    assert r.status_code == 200
    # end with a tz-aware end_at too
    r2 = c.post("/api/fasting/end", json={"end_at": "2026-08-04T18:00:00+05:30"})
    assert r2.status_code == 200
    assert r2.get_json()["fast"]["status"] == "completed"


def test_future_end_clamped_to_now(app):
    _, uid = _uid(app, "fast9@medeasy.test")
    with user_context(uid):
        start_fast(16, start_at=_ago(5))
        # An end 100h in the future is impossible → falls back to now (~5h).
        done = end_fast(end_at=(_dt.datetime.now() + _dt.timedelta(hours=100)).isoformat())
        assert done["duration_hours"] == pytest.approx(5, abs=0.1)


def test_api_round_trip(app):
    c, uid = _uid(app, "fast7@medeasy.test")
    r = c.post("/api/fasting/start", json={"target_hours": 18, "start_at": _ago(6)})
    assert r.status_code == 200 and r.get_json()["fast"]["target_hours"] == 18
    # can't start a second while one is active
    assert c.post("/api/fasting/start", json={"target_hours": 20}).status_code == 400
    listed = c.get("/api/fasting").get_json()
    assert listed["active"]["elapsed_hours"] == pytest.approx(6, abs=0.1)
    ended = c.post("/api/fasting/end", json={}).get_json()
    assert ended["fast"]["status"] == "completed"
    assert c.get("/api/fasting").get_json()["active"] is None
