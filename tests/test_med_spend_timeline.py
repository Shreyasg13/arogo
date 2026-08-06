"""Medication spend over time — monthly estimate + YTD + projected annual."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import get_med_spend_timeline, insert_medicine

PW = "spend-pw-12345"


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


def test_empty_when_no_priced_meds(app):
    _, uid = _uid(app, "spend1@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Free med", "frequency": "once_daily", "times": ["09:00"]})  # no cost
        d = get_med_spend_timeline()
    assert d["has_data"] is False and d["current_monthly"] == 0.0


def test_current_month_and_projection(app):
    _, uid = _uid(app, "spend2@medeasy.test")
    old_start = (dt.date.today() - dt.timedelta(days=200)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "Metformin", "frequency": "once_daily", "times": ["09:00"],
                         "cost": 300, "start_date": old_start})
        insert_medicine({"name": "Losartan", "frequency": "once_daily", "times": ["08:00"],
                         "cost": 200, "start_date": old_start})
        d = get_med_spend_timeline(months=12)
    assert d["current_monthly"] == 500.0
    assert d["projected_annual"] == 6000.0
    assert d["timeline"][-1]["spend"] == 500.0
    # a med that started ~200d ago is on in the current month and several prior
    assert sum(1 for t in d["timeline"] if t["spend"] == 500.0) >= 6


def test_med_not_counted_before_it_started(app):
    _, uid = _uid(app, "spend3@medeasy.test")
    recent_start = (dt.date.today() - dt.timedelta(days=20)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "NewMed", "frequency": "once_daily", "times": ["09:00"],
                         "cost": 400, "start_date": recent_start})
        d = get_med_spend_timeline(months=6)
    # current month counts it; the earliest months (months ago) should be 0
    assert d["timeline"][-1]["spend"] == 400.0
    assert d["timeline"][0]["spend"] == 0.0


def test_api(app):
    c, uid = _uid(app, "spend4@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Aspirin", "frequency": "once_daily", "times": ["09:00"],
                         "cost": 100, "start_date": (dt.date.today() - dt.timedelta(days=60)).isoformat()})
    body = c.get("/api/medicines/spend-timeline").get_json()
    assert body["current_monthly"] == 100.0 and "timeline" in body
