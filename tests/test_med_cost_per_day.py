"""I9 — cost per day per medication. Each priced medicine's monthly cost broken
down to a per-day figure and ranked. Unpriced meds are counted, never assumed
₹0 (which would understate the total)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import insert_medicine, get_cost_per_day

PW = "cpd-pw-123456"
DPM = 30.437


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


def test_empty_without_priced_meds(app):
    _, uid = _uid(app, "cpd1@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Unpriced", "frequency": "once_daily", "times": ["09:00"]})
        d = get_cost_per_day()
    assert d["has_data"] is False and d["items"] == [] and d["unpriced"] == 1


def test_per_day_math_and_ranking(app):
    _, uid = _uid(app, "cpd2@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Cheap", "frequency": "once_daily", "times": ["09:00"], "cost": 100})
        insert_medicine({"name": "Dear", "frequency": "once_daily", "times": ["09:00"], "cost": 900})
        d = get_cost_per_day()
    assert d["has_data"] is True
    assert d["items"][0]["name"] == "Dear"          # priciest first
    assert d["items"][0]["per_day"] == round(900 / DPM, 2)
    assert d["items"][1]["per_day"] == round(100 / DPM, 2)
    assert d["total_per_month"] == 1000
    assert d["total_per_day"] == round(round(900/DPM, 2) + round(100/DPM, 2), 2)


def test_unpriced_not_assumed_zero(app):
    _, uid = _uid(app, "cpd3@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Priced", "frequency": "once_daily", "times": ["09:00"], "cost": 300})
        insert_medicine({"name": "NoPrice", "frequency": "once_daily", "times": ["09:00"]})
        d = get_cost_per_day()
    assert len(d["items"]) == 1 and d["unpriced"] == 1
    assert d["total_per_month"] == 300     # the unpriced med adds nothing, isn't a ₹0 line


def test_api(app):
    c, uid = _uid(app, "cpd4@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"], "cost": 200})
    body = c.get("/api/medicines/cost-per-day").get_json()
    assert body["has_data"] is True and body["items"][0]["monthly"] == 200
