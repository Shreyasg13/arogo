"""Medication run-out forecast + cost projection."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import get_med_forecast, update_medicine_stock

PW = "fc-pw-123456"


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


def _med(c, name, cost=None, frequency="once_daily"):
    body = {"name": name, "frequency": frequency, "times": ["09:00"]}
    if cost is not None:
        body["cost"] = cost
    return c.post("/api/medicines", json=body).get_json()["medicine"]["id"]


def test_run_out_date(app):
    c, uid = _uid(app, "fc1@medeasy.test")
    mid = _med(c, "Metformin")
    with user_context(uid):
        update_medicine_stock(mid, pill_count=30, pills_per_dose=1)   # 1/day → 30 days
        f = get_med_forecast()
    ro = next(r for r in f["run_outs"] if r["id"] == mid)
    assert ro["days_left"] == 30
    expected = (_dt.date.today() + _dt.timedelta(days=30)).isoformat()
    assert ro["run_out"] == expected


def test_low_flag(app):
    c, uid = _uid(app, "fc2@medeasy.test")
    mid = _med(c, "Losartan")
    with user_context(uid):
        update_medicine_stock(mid, pill_count=3, pills_per_dose=1, refill_threshold=7)
        f = get_med_forecast()
    ro = next(r for r in f["run_outs"] if r["id"] == mid)
    assert ro["low"] is True and f["next_runout"]["id"] == mid   # soonest run-out first


def test_cost_projection(app):
    c, uid = _uid(app, "fc3@medeasy.test")
    _med(c, "A", cost=500)
    _med(c, "B", cost=250)
    _med(c, "C")                       # unpriced → excluded from cost
    with user_context(uid):
        f = get_med_forecast()
    assert f["monthly_cost"] == 750 and f["yearly_cost"] == 9000 and f["priced_count"] == 2


def test_untracked_meds_have_no_runout(app):
    c, uid = _uid(app, "fc4@medeasy.test")
    _med(c, "NoPills")                 # no pill_count set
    with user_context(uid):
        f = get_med_forecast()
    assert f["run_outs"] == [] and f["next_runout"] is None


def test_as_needed_has_no_runout_but_still_costs(app):
    # A PRN med has no daily schedule, so forecasting a run-out date would assume
    # 1 dose/day and invent a countdown — omit it from run_outs. Its cost still
    # counts toward the monthly projection.
    c, uid = _uid(app, "fc6@medeasy.test")
    mid = _med(c, "Rescue Inhaler", cost=300, frequency="as_needed")
    with user_context(uid):
        update_medicine_stock(mid, pill_count=200, pills_per_dose=1)
        f = get_med_forecast()
    assert all(r["id"] != mid for r in f["run_outs"])       # no fabricated run-out
    assert f["monthly_cost"] == 300                          # cost still projected


def test_api_endpoint(app):
    c, uid = _uid(app, "fc5@medeasy.test")
    mid = _med(c, "Aspirin", cost=100)
    with user_context(uid):
        update_medicine_stock(mid, pill_count=14, pills_per_dose=1)
    body = c.get("/api/medicines/forecast").get_json()
    assert body["monthly_cost"] == 100 and body["run_outs"][0]["days_left"] == 14
