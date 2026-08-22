"""Insurance policies + renewal countdown — stores what you entered, rates nothing."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today
from db.insurance import (create_policy, update_policy, delete_policy, get_policy,
                          list_policies, RENEWAL_SOON_DAYS)

PW = "ins-pw-12345"


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


def _in_days(n):
    return (dt.date.fromisoformat(user_today()) + dt.timedelta(days=n)).isoformat()


def test_insurer_required(app):
    _, uid = _uid(app, "pol1@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_policy({"insurer": "  "})


def test_create_and_renewal_countdown(app):
    _, uid = _uid(app, "pol2@medeasy.test")
    with user_context(uid):
        p = create_policy({"insurer": "Acme Health", "policy_no": "AC-1",
                           "kind": "health", "cover_amount": 500000,
                           "premium": 12000, "premium_period": "year",
                           "renewal_date": _in_days(10)})
    assert p["days_to_renewal"] == 10
    assert p["renewal_status"] == "soon"          # inside the 30-day window
    assert p["insurer"] == "Acme Health"


def test_no_renewal_date_says_nothing(app):
    _, uid = _uid(app, "pol3@medeasy.test")
    with user_context(uid):
        p = create_policy({"insurer": "NoDate Co"})
    assert p["days_to_renewal"] is None           # never guesses a date
    assert p["renewal_status"] == "unknown"


def test_expired_and_ok_statuses(app):
    _, uid = _uid(app, "pol4@medeasy.test")
    with user_context(uid):
        past = create_policy({"insurer": "Lapsed", "renewal_date": _in_days(-5)})
        far = create_policy({"insurer": "Fine", "renewal_date": _in_days(RENEWAL_SOON_DAYS + 60)})
    assert past["renewal_status"] == "expired" and past["days_to_renewal"] == -5
    assert far["renewal_status"] == "ok"


def test_yearly_premium_normalises_period(app):
    _, uid = _uid(app, "pol5@medeasy.test")
    with user_context(uid):
        create_policy({"insurer": "A", "premium": 1000, "premium_period": "month"})   # 12000/yr
        create_policy({"insurer": "B", "premium": 5000, "premium_period": "year"})    # 5000/yr
        create_policy({"insurer": "C"})                                               # no premium
        s = list_policies()["summary"]
    assert s["yearly_premium"] == 17000.0
    assert s["active"] == 3


def test_renewing_soon_surfaces_only_relevant(app):
    _, uid = _uid(app, "pol6@medeasy.test")
    with user_context(uid):
        create_policy({"insurer": "Soon", "renewal_date": _in_days(5)})
        create_policy({"insurer": "Later", "renewal_date": _in_days(200)})
        s = list_policies()["summary"]
    names = {r["insurer"] for r in s["renewing_soon"]}
    assert names == {"Soon"}


def test_update_and_delete_and_isolation(app):
    _, a = _uid(app, "pol7a@medeasy.test")
    _, b = _uid(app, "pol7b@medeasy.test")
    with user_context(a):
        p = create_policy({"insurer": "Mine"})
        p2 = update_policy(p["id"], {"insurer": "Renamed", "premium": 900})
        assert p2["insurer"] == "Renamed" and p2["premium"] == 900
    with user_context(b):
        assert get_policy(p["id"]) is None            # B can't see A's policy
        assert list_policies()["policies"] == []
        with pytest.raises(ValueError):
            update_policy(p["id"], {"insurer": "hack"})
    with user_context(a):
        delete_policy(p["id"])
        assert get_policy(p["id"]) is None


def test_routes(app):
    c, _ = _uid(app, "pol8@medeasy.test")
    assert c.get("/api/insurance").status_code == 200
    r = c.post("/api/insurance", json={"insurer": "RouteCo", "renewal_date": _in_days(3)}).get_json()
    assert r["success"] and r["policy"]["days_to_renewal"] == 3
    pid = r["policy"]["id"]
    assert c.patch(f"/api/insurance/{pid}", json={"premium": 100}).get_json()["success"]
    assert c.delete(f"/api/insurance/{pid}").get_json()["success"]


def test_route_requires_auth(app):
    assert app.test_client().get("/api/insurance").status_code in (401, 403)
