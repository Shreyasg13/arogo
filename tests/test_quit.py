"""O2 quit tracker — days free, units avoided, money saved, all computed from the
user's OWN quit date, baseline and unit cost. Nothing invented; None when unset."""
import datetime as dt
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db

PW = "quit-pw-1234567"


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


def test_derived_savings_from_own_inputs(app):
    c = _reg(app, "quit1@medeasy.test")
    # 10 days ago, 10 cigarettes/day at ₹15 each.
    p = c.post("/api/quit", json={"kind": "smoking", "quit_date": _days_ago(10),
                                  "baseline_per_day": 10, "unit_cost": 15}).get_json()["plan"]
    assert p["days_free"] == 10
    assert p["units_avoided"] == 100          # 10/day * 10 days
    assert p["money_saved"] == 1500.0         # 100 * ₹15


def test_null_baseline_gives_null_not_zero(app):
    c = _reg(app, "quit2@medeasy.test")
    p = c.post("/api/quit", json={"kind": "alcohol", "quit_date": _days_ago(5)}).get_json()["plan"]
    assert p["days_free"] == 5
    assert p["units_avoided"] is None and p["money_saved"] is None   # no invented savings


def test_quit_date_required(app):
    c = _reg(app, "quit3@medeasy.test")
    assert c.post("/api/quit", json={"kind": "smoking", "quit_date": "soon"}).status_code == 400


def test_reset_quit_date(app):
    c = _reg(app, "quit4@medeasy.test")
    p = c.post("/api/quit", json={"quit_date": _days_ago(30), "baseline_per_day": 5}).get_json()["plan"]
    r = c.patch(f"/api/quit/{p['id']}", json={"quit_date": _days_ago(2)})
    assert r.status_code == 200 and r.get_json()["plan"]["days_free"] == 2


def test_user_scoped(app):
    a = _reg(app, "quit5a@medeasy.test"); b = _reg(app, "quit5b@medeasy.test")
    p = a.post("/api/quit", json={"quit_date": _days_ago(1)}).get_json()["plan"]
    assert b.get("/api/quit").get_json()["plans"] == []
    assert b.patch(f"/api/quit/{p['id']}", json={"quit_date": _days_ago(3)}).status_code == 404
