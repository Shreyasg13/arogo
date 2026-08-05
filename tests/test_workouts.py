"""Structured strength log — sets/reps/weight, sessions, and 1RM progression."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.workouts import (log_set, delete_set, list_exercises, get_workout_log,
                         get_progression, epley_1rm, _exercise_key)

PW = "wk-pw-123456"


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


def test_epley_and_key():
    assert epley_1rm(100, 1) == 100.0            # single rep = the weight
    assert epley_1rm(100, 5) == round(100 * (1 + 5 / 30), 1)
    assert epley_1rm(0, 10) == 0.0               # bodyweight: no load to project
    assert epley_1rm(100, 0) == 0.0
    assert _exercise_key("  Bench  PRESS ") == "bench press"


def test_log_requires_exercise_and_reps(app):
    _, uid = _uid(app, "wk1@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            log_set({"exercise": "", "reps": 5})
        with pytest.raises(ValueError):
            log_set({"exercise": "Squat", "reps": 0})


def test_session_grouping_and_volume(app):
    _, uid = _uid(app, "wk2@medeasy.test")
    with user_context(uid):
        log_set({"exercise": "Bench Press", "reps": 10, "weight": 60, "date_key": "2026-08-01"})
        log_set({"exercise": "bench press", "reps": 8, "weight": 65, "date_key": "2026-08-01"})  # same session (norm key)
        log_set({"exercise": "Squat", "reps": 5, "weight": 100, "date_key": "2026-08-01"})
        log = get_workout_log(days=3650)
        bench = next(s for s in log["sessions"] if s["exercise"].lower() == "bench press")
        assert len(bench["sets"]) == 2
        assert bench["volume"] == 10 * 60 + 8 * 65     # 1120
        assert bench["top_weight"] == 65
        assert bench["best_1rm"] == max(epley_1rm(60, 10), epley_1rm(65, 8))
        # Two distinct exercises on one day → two sessions
        assert len({(s["date_key"], s["exercise"].lower()) for s in log["sessions"]}) == 2


def test_progression_oldest_to_newest_and_pb(app):
    _, uid = _uid(app, "wk3@medeasy.test")
    with user_context(uid):
        log_set({"exercise": "Deadlift", "reps": 5, "weight": 100, "date_key": "2026-08-01"})
        log_set({"exercise": "Deadlift", "reps": 5, "weight": 110, "date_key": "2026-08-08"})
        log_set({"exercise": "Deadlift", "reps": 3, "weight": 120, "date_key": "2026-08-15"})
        prog = get_progression("deadlift")
        assert prog["has_data"] is True
        assert [p["date_key"] for p in prog["points"]] == ["2026-08-01", "2026-08-08", "2026-08-15"]
        assert prog["best_weight"] == 120
        assert prog["best_1rm"] == max(epley_1rm(100, 5), epley_1rm(110, 5), epley_1rm(120, 3))
        assert prog["display_name"] == "Deadlift"


def test_progression_empty_for_unknown(app):
    _, uid = _uid(app, "wk4@medeasy.test")
    with user_context(uid):
        prog = get_progression("Overhead Press")
        assert prog["has_data"] is False and prog["points"] == [] and prog["best_1rm"] == 0


def test_list_exercises_distinct_recent_first(app):
    _, uid = _uid(app, "wk5@medeasy.test")
    with user_context(uid):
        log_set({"exercise": "Row", "reps": 10, "weight": 40, "date_key": "2026-08-01"})
        log_set({"exercise": "Curl", "reps": 12, "weight": 15, "date_key": "2026-08-02"})
        log_set({"exercise": "row", "reps": 10, "weight": 42, "date_key": "2026-08-03"})  # dup key
        ex = list_exercises()
        assert len([e for e in ex if e.lower() == "row"]) == 1     # de-duped by key
        assert set(e.lower() for e in ex) == {"row", "curl"}


def test_delete_and_isolation(app):
    ca, uid_a = _uid(app, "wk6@medeasy.test")
    _, uid_b = _uid(app, "wk7@medeasy.test")
    with user_context(uid_a):
        s = log_set({"exercise": "Pullup", "reps": 8, "weight": 0})
        delete_set(s["id"])
        assert get_workout_log()["has_data"] is False
        log_set({"exercise": "Dip", "reps": 10, "weight": 0})
    with user_context(uid_b):
        assert get_workout_log()["has_data"] is False        # B sees nothing of A's
        assert get_progression("Dip")["has_data"] is False


def test_api_round_trip(app):
    c, uid = _uid(app, "wk8@medeasy.test")
    assert c.post("/api/workouts", json={"exercise": "Bench Press", "reps": 5, "weight": 80}).status_code == 200
    log = c.get("/api/workouts").get_json()
    assert log["has_data"] is True
    prog = c.get("/api/workouts/progression?exercise=Bench Press").get_json()
    assert prog["best_weight"] == 80
    assert c.get("/api/workouts/exercises").get_json()["exercises"] == ["Bench Press"]
    assert c.post("/api/workouts", json={"exercise": "", "reps": 5}).status_code == 400
