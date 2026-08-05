"""Outcome health goals — progress derived honestly from logged values, across
the below / above / reach directions."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.goals import create_goal, list_goals, update_goal, latest_value

PW = "goal-pw-12345"


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


def _weight(uid, kg, date):
    execute("""INSERT INTO body_metrics (id,date_key,weight_kg,body_fat_pct,waist_cm,bmi,notes,created_at,user_id)
               VALUES (?,?,?,NULL,NULL,NULL,'',?,?)""",
            (new_id(), date, kg, now_iso(), uid), commit=True)


def _lab(uid, key, value, date):
    execute("""INSERT INTO lab_results (id,lab_key,name,value,unit,date_key,notes,created_at,user_id)
               VALUES (?,?,?,?,?,?,'',?,?)""",
            (new_id(), key, key, value, "", date, now_iso(), uid), commit=True)


def test_below_goal_progress(app):
    # Lose weight: start 80, target 70. At 75 → halfway (50%).
    c, uid = _uid(app, "goal1@medeasy.test")
    with user_context(uid):
        _weight(uid, 80, "2026-06-01")
        g = create_goal("weight", 70, "below")   # baseline captured = 80
        assert g["start_value"] == 80
        _weight(uid, 75, "2026-07-01")            # now at 75
        goals = list_goals()["goals"]
    wg = goals[0]
    assert wg["current"] == 75
    assert wg["progress"] == pytest.approx(0.5, abs=0.01)
    assert wg["auto_achieved"] is False


def test_below_goal_achieved(app):
    c, uid = _uid(app, "goal2@medeasy.test")
    with user_context(uid):
        _lab(uid, "hba1c", 7.5, "2026-06-01")
        create_goal("hba1c", 6.5, "below")
        _lab(uid, "hba1c", 6.2, "2026-07-01")     # below target
        g = list_goals()["goals"][0]
    assert g["auto_achieved"] is True and g["progress"] == 1.0


def test_reach_goal_steps(app):
    c, uid = _uid(app, "goal3@medeasy.test")
    with user_context(uid):
        execute("""INSERT INTO fitness_activities (id,type,date,steps,created_at,user_id)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), "walk", "2026-07-01", 6000, now_iso(), uid), commit=True)
        create_goal("steps", 8000, "reach")
        g = list_goals()["goals"][0]
    assert g["current"] == 6000 and g["progress"] == pytest.approx(0.75, abs=0.01)
    assert g["auto_achieved"] is False


def test_no_data_progress_is_none(app):
    c, uid = _uid(app, "goal4@medeasy.test")
    with user_context(uid):
        create_goal("ldl", 100, "below")          # nothing logged
        g = list_goals()["goals"][0]
    assert g["current"] is None and g["progress"] is None   # honest: can't compute


def test_status_and_filter(app):
    c, uid = _uid(app, "goal5@medeasy.test")
    with user_context(uid):
        g = create_goal("weight", 70, "below")
        update_goal(g["id"], {"status": "archived"})
        assert list_goals()["goals"] == []                  # archived hidden by default
        assert len(list_goals(include_done=True)["goals"]) == 1


def test_rejects_bad_input(app):
    _, uid = _uid(app, "goal6@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_goal("nonsense_metric", 5)
        with pytest.raises(ValueError):
            create_goal("weight", "abc")


def test_api_round_trip(app):
    c, uid = _uid(app, "goal7@medeasy.test")
    r = c.post("/api/goals", json={"metric": "weight", "target_value": 68, "direction": "below", "deadline": "2026-12-31"})
    assert r.status_code == 200
    gid = r.get_json()["goal"]["id"]
    assert c.get("/api/goals").get_json()["goals"][0]["metric"] == "weight"
    assert c.patch(f"/api/goals/{gid}", json={"status": "achieved"}).get_json()["goal"]["status"] == "achieved"
    assert c.get("/api/goals").get_json()["goals"] == []    # achieved hidden
    assert c.post("/api/goals", json={"metric": "weight", "target_value": "x"}).status_code == 400
