"""Refill shopping list: consolidated pharmacy-run checklist."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "rfl-pw-123456"


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


def _add(c, name, **stock):
    m = c.post("/api/medicines", json={
        "name": name, "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    if stock:
        c.post(f"/api/medicines/{m['id']}/stock", json=stock)
    return m


def test_only_low_out_or_ordered_meds_appear(app):
    c = _register(app, "rfl1@medeasy.test")
    _add(c, "PlentyLeft", pill_count=90, pills_per_dose=1, refill_threshold=7)  # ~90d — fine
    _add(c, "RunningLow", pill_count=3,  pills_per_dose=1, refill_threshold=7)  # ~3d — low
    _add(c, "Untracked")                                                        # no pill count
    items = c.get("/api/medicines/refill-list").get_json()["items"]
    names = [i["name"] for i in items]
    assert "RunningLow" in names
    assert "PlentyLeft" not in names and "Untracked" not in names


def test_out_of_stock_sorts_first_ordered_last(app):
    c = _register(app, "rfl2@medeasy.test")
    _add(c, "Low",  pill_count=4, pills_per_dose=1, refill_threshold=10)
    _add(c, "Empty", pill_count=0, pills_per_dose=1, refill_threshold=10)
    ordered = _add(c, "Ordered", pill_count=2, pills_per_dose=1, refill_threshold=10)
    c.post(f"/api/medicines/{ordered['id']}/refill/ordered")

    items = c.get("/api/medicines/refill-list").get_json()["items"]
    names = [i["name"] for i in items]
    assert names[0] == "Empty"            # out of stock leads
    assert names[-1] == "Ordered"         # on-the-way sinks to the bottom
    empty = next(i for i in items if i["name"] == "Empty")
    assert empty["out"] is True
    assert next(i for i in items if i["name"] == "Ordered")["ordered"] is True


def test_empty_list_when_nothing_needs_refilling(app):
    c = _register(app, "rfl3@medeasy.test")
    _add(c, "WellStocked", pill_count=120, pills_per_dose=1, refill_threshold=7)
    assert c.get("/api/medicines/refill-list").get_json()["items"] == []


def test_refill_list_requires_auth(app):
    assert app.test_client().get("/api/medicines/refill-list").status_code == 401
