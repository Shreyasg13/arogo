"""M2 home medical-supplies inventory — first-aid + OTC basics with quantity,
optional expiry and a restock threshold. Factual inventory, user-scoped, with
expired / expiring / low-stock alerts derived only from the user's own numbers."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "sup-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def _days(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_add_list_and_category_filter(app):
    c = _reg(app, "sup1@medeasy.test")
    c.post("/api/supplies", json={"name": "Paracetamol 500", "category": "otc", "quantity": 20, "unit": "tablets"})
    c.post("/api/supplies", json={"name": "Digital thermometer", "category": "device", "quantity": 1})
    alls = c.get("/api/supplies").get_json()["supplies"]
    assert len(alls) == 2
    otc = c.get("/api/supplies?category=otc").get_json()["supplies"]
    assert len(otc) == 1 and otc[0]["name"] == "Paracetamol 500"


def test_name_required_and_bad_expiry_rejected(app):
    c = _reg(app, "sup2@medeasy.test")
    assert c.post("/api/supplies", json={"name": "", "quantity": 1}).status_code == 400
    assert c.post("/api/supplies", json={"name": "Gauze", "expiry_date": "whenever"}).status_code == 400


def test_alerts_expired_expiring_and_low(app):
    c = _reg(app, "sup3@medeasy.test")
    c.post("/api/supplies", json={"name": "Antiseptic", "expiry_date": _days(-3)})           # expired
    c.post("/api/supplies", json={"name": "ORS sachets", "expiry_date": _days(20)})           # expiring soon
    c.post("/api/supplies", json={"name": "Band-aids", "quantity": 2, "low_at": 5})           # low stock
    c.post("/api/supplies", json={"name": "Cotton", "quantity": 50, "low_at": 5})             # fine, no alert
    a = c.get("/api/supplies/alerts").get_json()
    assert [x["name"] for x in a["expired"]] == ["Antiseptic"]
    assert [x["name"] for x in a["expiring"]] == ["ORS sachets"]
    assert [x["name"] for x in a["low"]] == ["Band-aids"]
    assert a["total"] == 3


def test_low_stock_only_when_threshold_set(app):
    c = _reg(app, "sup4@medeasy.test")
    # quantity 0 but no low_at threshold → NOT flagged (honest: user didn't ask for a nudge)
    c.post("/api/supplies", json={"name": "Spare mask", "quantity": 0})
    assert c.get("/api/supplies/alerts").get_json()["low"] == []


def test_restock_update(app):
    c = _reg(app, "sup5@medeasy.test")
    s = c.post("/api/supplies", json={"name": "Ibuprofen", "quantity": 1, "low_at": 5}).get_json()["supply"]
    assert c.get("/api/supplies/alerts").get_json()["low"]        # low before restock
    r = c.patch(f"/api/supplies/{s['id']}", json={"quantity": 30})
    assert r.status_code == 200 and r.get_json()["supply"]["quantity"] == 30
    assert c.get("/api/supplies/alerts").get_json()["low"] == []  # cleared after restock


def test_user_scoped_and_foreign_patch_delete_noop(app):
    a = _reg(app, "sup6a@medeasy.test")
    b = _reg(app, "sup6b@medeasy.test")
    s = a.post("/api/supplies", json={"name": "Private kit", "quantity": 3}).get_json()["supply"]
    assert b.get("/api/supplies").get_json()["supplies"] == []
    assert b.patch(f"/api/supplies/{s['id']}", json={"quantity": 99}).status_code == 404
    b.delete(f"/api/supplies/{s['id']}")                      # no-op for A
    assert len(a.get("/api/supplies").get_json()["supplies"]) == 1


def test_requires_auth(app):
    anon = app.test_client()
    assert anon.get("/api/supplies").status_code in (401, 403)
    assert anon.get("/api/supplies/alerts").status_code in (401, 403)
