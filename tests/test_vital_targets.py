"""Personal vital target ranges — set a doctor's band, flag out-of-band readings."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.vital_targets import set_target, clear_target, get_targets, flag

PW = "vt-pw-123456"


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


def test_set_and_flag(app):
    _, uid = _uid(app, "vt1@medeasy.test")
    with user_context(uid):
        set_target("blood_pressure", None, 130)     # keep systolic under 130
        assert flag("blood_pressure", 145) == "above"
        assert flag("blood_pressure", 120) == "in"
        set_target("blood_sugar", 80, 110)
        assert flag("blood_sugar", 70) == "below"
        assert flag("blood_sugar", 95) == "in"
        assert flag("blood_sugar", 130) == "above"


def test_no_target_no_flag(app):
    _, uid = _uid(app, "vt2@medeasy.test")
    with user_context(uid):
        assert flag("heart_rate", 200) is None       # no target set → no flag


def test_validation(app):
    _, uid = _uid(app, "vt3@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            set_target("not_a_vital", 1, 2)
        with pytest.raises(ValueError):
            set_target("weight", None, None)          # need at least one bound


def test_swapped_bounds_tolerated(app):
    _, uid = _uid(app, "vt4@medeasy.test")
    with user_context(uid):
        t = set_target("blood_sugar", 110, 80)        # hi/lo swapped
    assert t["target_min"] == 80 and t["target_max"] == 110


def test_set_replaces_and_clear(app):
    _, uid = _uid(app, "vt5@medeasy.test")
    with user_context(uid):
        set_target("weight", 60, 70)
        set_target("weight", 65, 75)                  # replaces, not duplicates
        rows = execute("SELECT * FROM vital_targets WHERE user_id=? AND vtype='weight'", (uid,), fetchall=True)
        assert len(rows) == 1 and get_targets()["weight"]["target_min"] == 65
        clear_target("weight")
        assert "weight" not in get_targets()


def test_isolation(app):
    _, uid_a = _uid(app, "vt6@medeasy.test")
    _, uid_b = _uid(app, "vt7@medeasy.test")
    with user_context(uid_a):
        set_target("blood_pressure", None, 120)
    with user_context(uid_b):
        assert get_targets() == {}


def test_api_round_trip(app):
    c, uid = _uid(app, "vt8@medeasy.test")
    assert c.post("/api/vital-targets", json={"vtype": "blood_sugar", "target_min": 80, "target_max": 110}).status_code == 200
    assert c.get("/api/vital-targets").get_json()["targets"]["blood_sugar"]["target_max"] == 110
    assert c.delete("/api/vital-targets/blood_sugar").get_json()["success"] is True
    assert c.get("/api/vital-targets").get_json()["targets"] == {}
    assert c.post("/api/vital-targets", json={"vtype": "x"}).status_code == 400
