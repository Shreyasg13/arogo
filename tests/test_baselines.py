"""J7 — "your own normal". Personal baseline bands (mean ± 1 SD) per vital from
the user's own readings, with where the latest sits. Descriptive stats of own
logs; needs enough readings to mean anything."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.baselines import get_personal_baselines, _MIN_N

PW = "base-pw-12345"


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


def _bp(uid, sys, day):
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), day, "blood_pressure", sys, 80, "mmHg", f"{day}T09:00:00", uid), commit=True)


def _day(i):
    import datetime as dt
    return (dt.date.today() - dt.timedelta(days=i)).isoformat()


def test_needs_enough_readings(app):
    _, uid = _uid(app, "base1@medeasy.test")
    with user_context(uid):
        for i in range(_MIN_N - 1):        # one short of the threshold
            _bp(uid, 120, _day(i))
        d = get_personal_baselines()
    assert d["has_data"] is False


def test_baseline_mean_and_band(app):
    _, uid = _uid(app, "base2@medeasy.test")
    with user_context(uid):
        # 10 systolic readings averaging 120 with spread → a band forms.
        for i, v in enumerate([118, 122, 120, 124, 116, 121, 119, 123, 117, 120]):
            _bp(uid, v, _day(i))
        d = get_personal_baselines()
    m = next(x for x in d["metrics"] if x["key"] == "systolic")
    assert m["count"] == 10
    assert 119 <= m["mean"] <= 121                 # ~120
    assert m["low"] < m["mean"] < m["high"]        # a real ±SD band
    assert m["unit"] == "mmHg"


def test_latest_position_flags(app):
    _, uid = _uid(app, "base3@medeasy.test")
    with user_context(uid):
        # Tight cluster around 120, then a latest reading well above.
        for i in range(9):
            _bp(uid, 120, _day(i + 1))
        _bp(uid, 150, _day(0))          # today, clearly above the band
        d = get_personal_baselines()
    m = next(x for x in d["metrics"] if x["key"] == "systolic")
    assert m["latest"] == 150 and m["position"] == "above"


def test_api(app):
    c, uid = _uid(app, "base4@medeasy.test")
    with user_context(uid):
        for i in range(_MIN_N):
            _bp(uid, 118 + i, _day(i))
    body = c.get("/api/vitals/baselines").get_json()
    assert body["has_data"] is True
    assert any(m["key"] == "systolic" for m in body["metrics"])
