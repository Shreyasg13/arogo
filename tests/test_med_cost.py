"""Medication cost tracking: per-med monthly cost + total spend."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "cost-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _add(c, name, **extra):
    body = {"name": name, "frequency": "once_daily", "times": ["09:00"]}
    body.update(extra)
    return c.post("/api/medicines", json=body).get_json()["medicine"]


def test_cost_is_stored_and_totalled_dearest_first(app):
    c = _register(app, "cost1@medeasy.test")
    _add(c, "Cheap", cost=120)
    _add(c, "Dear", cost=800.50)
    _add(c, "Unpriced")                       # no cost → excluded, not counted as 0
    summary = c.get("/api/medicines/cost").get_json()
    assert summary["total"] == 920.5 and summary["count"] == 2
    assert [i["name"] for i in summary["items"]] == ["Dear", "Cheap"]   # dearest first


def test_blank_cost_is_null_not_zero(app):
    c = _register(app, "cost2@medeasy.test")
    m = _add(c, "NoCost", cost="")
    assert m["cost"] is None
    assert c.get("/api/medicines/cost").get_json()["count"] == 0


def test_negative_cost_is_clamped_to_zero(app):
    c = _register(app, "cost3@medeasy.test")
    m = _add(c, "Weird", cost=-50)
    assert m["cost"] == 0.0


def test_cost_requires_auth(app):
    assert app.test_client().get("/api/medicines/cost").status_code == 401
