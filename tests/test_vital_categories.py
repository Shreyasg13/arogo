"""BP & resting-HR categories — standard published bands, per-reading + distribution."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import classify_bp, classify_hr, get_vital_categories, log_vital

PW = "vcat-pw-12345"


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


def test_bp_bands():
    assert classify_bp(115, 75)[0] == "normal"
    assert classify_bp(125, 78)[0] == "elevated"
    assert classify_bp(135, 78)[0] == "stage1"     # systolic drives it
    assert classify_bp(118, 82)[0] == "stage1"     # diastolic drives it (worse of the two)
    assert classify_bp(145, 85)[0] == "stage2"
    assert classify_bp(185, 100)[0] == "crisis"
    assert classify_bp(None, 80)[0] is None


def test_hr_bands():
    assert classify_hr(55)[0] == "low"
    assert classify_hr(70)[0] == "normal"
    assert classify_hr(110)[0] == "high"
    assert classify_hr("x")[0] is None


def test_categories_distribution(app):
    import datetime as dt
    _, uid = _uid(app, "vcat1@medeasy.test")

    def _day(n):
        return (dt.date.today() - dt.timedelta(days=n)).isoformat()

    with user_context(uid):
        log_vital({"type": "blood_pressure", "value1": 118, "value2": 76, "date_key": _day(3)})  # normal
        log_vital({"type": "blood_pressure", "value1": 135, "value2": 85, "date_key": _day(2)})  # stage1
        log_vital({"type": "blood_pressure", "value1": 150, "value2": 95, "date_key": _day(0)})  # stage2, today
        log_vital({"type": "heart_rate", "value1": 72})                      # normal
        d = get_vital_categories()
    assert d["has_data"] is True
    bp_dist = {x["band"]: x["count"] for x in d["bp"]["distribution"]}
    assert bp_dist["normal"] == 1 and bp_dist["stage1"] == 1 and bp_dist["stage2"] == 1
    assert d["bp"]["total"] == 3
    assert d["bp"]["latest"]["band"] == "stage2"     # newest first
    assert d["hr"]["latest"]["band"] == "normal"


def test_isolation_and_api(app):
    c, uid_a = _uid(app, "vcat2@medeasy.test")
    _, uid_b = _uid(app, "vcat3@medeasy.test")
    with user_context(uid_a):
        log_vital({"type": "blood_pressure", "value1": 145, "value2": 92})
    body = c.get("/api/vitals/categories").get_json()
    assert body["has_data"] is True and body["bp"]["latest"]["band"] == "stage2"
    with user_context(uid_b):
        assert get_vital_categories()["has_data"] is False
