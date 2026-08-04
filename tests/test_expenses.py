"""Health spending tracker — out-of-pocket totals, insurance/scheme offset,
per-category breakdown, month bounds."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.expenses import log_expense, get_month, recent_months, delete_expense

PW = "exp-pw-12345"


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


def test_net_is_amount_minus_covered(app):
    _, uid = _uid(app, "exp1@medeasy.test")
    with user_context(uid):
        e = log_expense("consultation", 800, "2026-07-10", covered=500)
    assert e["net"] == 300.0


def test_covered_capped_at_amount(app):
    _, uid = _uid(app, "exp2@medeasy.test")
    with user_context(uid):
        e = log_expense("lab", 1200, "2026-07-10", covered=5000)   # scheme "over-paid"
    assert e["covered"] == 1200.0 and e["net"] == 0.0


def test_month_summary_and_breakdown(app):
    _, uid = _uid(app, "exp3@medeasy.test")
    with user_context(uid):
        log_expense("medicines", 1000, "2026-07-05")
        log_expense("lab", 2000, "2026-07-20", covered=500)
        log_expense("consultation", 600, "2026-06-30")     # different month
        s = get_month("2026-07")
    assert s["count"] == 2
    assert s["total"] == 3000.0 and s["covered"] == 500.0 and s["out_of_pocket"] == 2500.0
    # breakdown is net per category, largest first
    assert s["breakdown"][0] == {"category": "lab", "net": 1500.0}
    assert {"category": "medicines", "net": 1000.0} in s["breakdown"]


def test_unknown_category_falls_to_other(app):
    _, uid = _uid(app, "exp4@medeasy.test")
    with user_context(uid):
        e = log_expense("spaceship", 100, "2026-07-01")
    assert e["category"] == "other"


def test_rejects_non_positive_amount(app):
    _, uid = _uid(app, "exp5@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            log_expense("lab", 0, "2026-07-01")
        with pytest.raises(ValueError):
            log_expense("lab", "abc", "2026-07-01")


def test_recent_months_oldest_first(app):
    _, uid = _uid(app, "exp6@medeasy.test")
    with user_context(uid):
        log_expense("medicines", 500, "2026-05-10")
        log_expense("medicines", 700, "2026-07-10", covered=200)
        months = recent_months(6)
    assert [m["month"] for m in months] == ["2026-05", "2026-07"]
    assert months[-1]["out_of_pocket"] == 500.0    # 700 - 200


def test_api_round_trip(app):
    c, uid = _uid(app, "exp7@medeasy.test")
    r = c.post("/api/expenses", json={"category": "medicines", "amount": 450,
                                      "date_key": "2026-07-15", "description": "BP meds"})
    assert r.status_code == 200 and r.get_json()["expense"]["net"] == 450.0
    s = c.get("/api/expenses?month=2026-07").get_json()
    assert s["out_of_pocket"] == 450.0
    assert c.get("/api/expenses/trend").get_json()["months"]
    assert "medicines" in c.get("/api/expenses/meta").get_json()["categories"]
    # bad amount rejected
    assert c.post("/api/expenses", json={"category": "lab", "amount": -5,
                                         "date_key": "2026-07-15"}).status_code == 400
