"""O4 pregnancy tracker — a profile (LMP/due → computed current week) plus dated
weight/kick logs. Tracking only; no medical guidance. User-scoped."""
import datetime as dt
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db

PW = "preg-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client(); c.post("/auth/register", json={"email": email, "password": PW}); return c


def _days_ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def test_week_computed_from_lmp(app):
    c = _reg(app, "preg1@medeasy.test")
    p = c.post("/api/pregnancy", json={"lmp_date": _days_ago(70)}).get_json()["pregnancy"]   # 10 weeks
    assert p["active"] is True and p["week"] == 10 and p["day_in_week"] == 0
    # Due date auto-filled 280 days from LMP.
    assert p["due_date"] == (dt.date.today() - dt.timedelta(days=70) + dt.timedelta(days=280)).isoformat()


def test_requires_lmp_or_due(app):
    c = _reg(app, "preg2@medeasy.test")
    assert c.post("/api/pregnancy", json={}).status_code == 400
    assert c.post("/api/pregnancy", json={"lmp_date": "bad"}).status_code == 400


def test_logs_and_end(app):
    c = _reg(app, "preg3@medeasy.test")
    c.post("/api/pregnancy", json={"lmp_date": _days_ago(140)})
    c.post("/api/pregnancy/log", json={"date_key": _days_ago(1), "weight_kg": 64.5, "kicks": 12})
    d = c.get("/api/pregnancy").get_json()
    assert d["pregnancy"]["active"] is True and len(d["logs"]) == 1
    assert d["logs"][0]["kicks"] == 12 and d["logs"][0]["weight_kg"] == 64.5
    # Ending clears the active profile and its logs list.
    c.post("/api/pregnancy/end")
    d2 = c.get("/api/pregnancy").get_json()
    assert d2["pregnancy"]["active"] is False and d2["logs"] == []


def test_log_without_active_pregnancy_rejected(app):
    c = _reg(app, "preg4@medeasy.test")
    assert c.post("/api/pregnancy/log", json={"weight_kg": 60}).status_code == 400


def test_user_scoped(app):
    a = _reg(app, "preg5a@medeasy.test"); b = _reg(app, "preg5b@medeasy.test")
    a.post("/api/pregnancy", json={"lmp_date": _days_ago(30)})
    assert b.get("/api/pregnancy").get_json()["pregnancy"]["active"] is False


def test_requires_auth(app):
    assert app.test_client().get("/api/pregnancy").status_code in (401, 403)
