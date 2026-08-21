"""Environment (AQI) import + correlation with how you feel — honest, no causation."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db.environment import (parse_environment_csv, commit_environment, list_environment,
                            get_environment_correlation, MIN_PAIRS)

PW = "env-pw-12345"


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


def _ago(n):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=n)).isoformat()


def _symptom(uid, date_key, name="Cough"):
    execute("INSERT INTO symptoms (id,name,severity,date_key,logged_at,user_id) VALUES (?,?,?,?,?,?)",
            (new_id(), name, 5, date_key, now_iso(), uid), commit=True)


# ── CSV parse ────────────────────────────────────────────────────────────────

def test_parse_detects_columns_and_saves_nothing(app):
    _, uid = _uid(app, "env1@medeasy.test")
    csv = "Date,US AQI,Temperature,Humidity\n2026-08-01,142,31,70\n02/08/2026,88,30,65\nbad,,,\n"
    with user_context(uid):
        d = parse_environment_csv(csv)
        # parse must not write
        n = execute("SELECT COUNT(*) c FROM environment_days WHERE user_id=?", (uid,), fetchone=True)["c"]
    assert d["detected"] == {"aqi": True, "temp": True, "humidity": True}
    assert len(d["candidates"]) == 2 and d["skipped"] == 1   # bad row skipped
    assert d["candidates"][0]["aqi"] == 142.0
    assert n == 0


def test_parse_needs_date_and_aqi(app):
    d = parse_environment_csv("City,Note\nDelhi,hi\n")
    assert d["candidates"] == [] and d["detected"] is None


def test_commit_upserts_by_day(app):
    _, uid = _uid(app, "env2@medeasy.test")
    with user_context(uid):
        commit_environment([{"date_key": "2026-08-01", "aqi": 100}])
        commit_environment([{"date_key": "2026-08-01", "aqi": 150}])   # same day → replace
        rows = list_environment(3650)
    assert len(rows) == 1 and rows[0]["aqi"] == 150.0


# ── correlation ──────────────────────────────────────────────────────────────

def test_correlation_needs_enough_shared_days(app):
    _, uid = _uid(app, "env3@medeasy.test")
    with user_context(uid):
        commit_environment([{"date_key": _ago(2), "aqi": 120}])
        _symptom(uid, _ago(2))
        d = get_environment_correlation("symptoms", 90)
    assert d["has_data"] is False and d["n"] < MIN_PAIRS
    assert "not proof" in d["caveat"].lower()


def test_correlation_moves_together(app):
    _, uid = _uid(app, "env4@medeasy.test")
    with user_context(uid):
        # higher AQI days → more symptom entries; lower AQI → fewer
        plan = [(20, 60, 0), (19, 65, 0), (18, 70, 1), (17, 180, 3),
                (16, 190, 3), (15, 200, 4), (14, 210, 4), (13, 55, 0)]
        for ago, aqi, sym in plan:
            commit_environment([{"date_key": _ago(ago), "aqi": aqi}])
            for _ in range(sym):
                _symptom(uid, _ago(ago))
        d = get_environment_correlation("symptoms", 90)
    assert d["has_data"] is True and d["n"] >= MIN_PAIRS
    assert d["r"] is not None and d["r"] > 0.4           # positive correlation
    assert d["direction"] == "together"
    # honesty: never a causal statement, always the caveat
    assert "caused" not in d["caveat"].lower() or "not proof" in d["caveat"].lower()


def test_routes(app):
    c, _ = _uid(app, "env5@medeasy.test")
    pv = c.post("/api/environment/import/preview", json={"csv": "date,aqi\n2026-08-01,90\n"}).get_json()
    assert len(pv["candidates"]) == 1
    cm = c.post("/api/environment/import/commit", json={"candidates": pv["candidates"]}).get_json()
    assert cm["success"] and cm["saved"] == 1
    assert c.get("/api/environment/correlation?target=symptoms").status_code == 200


def test_route_requires_auth(app):
    assert app.test_client().get("/api/environment").status_code in (401, 403)


def test_isolation(app):
    _, a = _uid(app, "env6a@medeasy.test")
    _, b = _uid(app, "env6b@medeasy.test")
    with user_context(a):
        commit_environment([{"date_key": _ago(1), "aqi": 111}])
    with user_context(b):
        assert list_environment(30) == []      # B never sees A's AQI import
