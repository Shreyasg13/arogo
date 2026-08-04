"""Body-recomposition signal — synthesises weight + body-fat + protein into one
honest read, so a young user isn't misled by the scale alone (muscle up + fat
down can leave weight flat). Gated hard; never a plan or a causal claim."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.food import get_recomp_signal, update_profile, log_food

PW = "recomp-pw-12345"


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


def _bm(uid, days_ago, weight=None, fat=None):
    d = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
    execute("""INSERT INTO body_metrics (id,date_key,weight_kg,body_fat_pct,waist_cm,bmi,notes,created_at,user_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (new_id(), d, weight, fat, None, None, '', now_iso(), uid), commit=True)


def test_no_data(app):
    _, uid = _uid(app, "rc0@medeasy.test")
    with user_context(uid):
        s = get_recomp_signal()
    assert s["has_data"] is False and s["read"] is None


def test_weight_change_needs_two_points(app):
    _, uid = _uid(app, "rc1@medeasy.test")
    with user_context(uid):
        _bm(uid, 10, weight=70)
        s = get_recomp_signal()
    # one weight reading → no weight block
    assert s["weight"] is None


def test_recomp_read_fat_down_weight_steady_protein_hit(app):
    c, uid = _uid(app, "rc2@medeasy.test")
    with user_context(uid):
        # give a bodyweight + gain goal so protein target exists (~1.6*70=112)
        update_profile({"weight_kg": 70, "height_cm": 175, "age": 24,
                        "gender": "male", "goal": "gain"})
        _bm(uid, 20, weight=70.0, fat=20.0)
        _bm(uid, 1,  weight=70.5, fat=17.5)      # fat down 2.5, weight steady
        # log plenty of protein today so avg clears 90% of target
        log_food({"food_name": "whey", "calories": 400, "protein": 130,
                  "carbs": 10, "fat": 5, "meal_type": "snack"})
        s = get_recomp_signal()
    assert s["read"] == "recomp"
    assert s["body_fat"]["change"] == -2.5
    assert s["protein"]["pct"] >= 90


def test_fat_loss_without_protein(app):
    _, uid = _uid(app, "rc3@medeasy.test")
    with user_context(uid):
        _bm(uid, 20, weight=80, fat=25)
        _bm(uid, 1,  weight=77, fat=22)          # fat down, weight down, no food logged
        s = get_recomp_signal()
    assert s["read"] == "fat_loss"


def test_protein_low_flag(app):
    c, uid = _uid(app, "rc4@medeasy.test")
    with user_context(uid):
        update_profile({"weight_kg": 60, "height_cm": 165, "age": 22,
                        "gender": "female", "goal": "maintain"})
        _bm(uid, 10, weight=60)
        _bm(uid, 1,  weight=60)                   # flat weight, no fat data
        log_food({"food_name": "toast", "calories": 200, "protein": 5,
                  "carbs": 40, "fat": 3, "meal_type": "breakfast"})
        s = get_recomp_signal()
    assert s["read"] == "protein_low"
    assert s["protein"]["pct"] < 70


def test_api_round_trip(app):
    c, uid = _uid(app, "rc5@medeasy.test")
    r = c.get("/api/body/recomp")
    assert r.status_code == 200
    assert "read" in r.get_json()
