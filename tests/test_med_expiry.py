"""K1 — medication expiry tracking. Track when a bottle/strip expires (distinct
from stock run-out); flag expired / soon-to-expire meds. Owner-scoped; never
invents a date."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import (insert_medicine, set_medicine_expiry,
                          get_expiring_medicines, get_medicine)

PW = "mexp-pw-12345"


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


def _d(offset):
    return (dt.date.today() + dt.timedelta(days=offset)).isoformat()


def test_expiry_stored_on_create(app):
    _, uid = _uid(app, "mexp1@medeasy.test")
    with user_context(uid):
        m = insert_medicine({"name": "Insulin", "frequency": "once_daily",
                             "times": ["09:00"], "expiry_date": _d(30)})
        assert m["expiry_date"] == _d(30)


def test_invalid_expiry_on_create_is_dropped(app):
    _, uid = _uid(app, "mexp2@medeasy.test")
    with user_context(uid):
        m = insert_medicine({"name": "X", "frequency": "once_daily",
                             "times": ["09:00"], "expiry_date": "not-a-date"})
        assert m["expiry_date"] == ""


def test_set_and_clear_expiry(app):
    _, uid = _uid(app, "mexp3@medeasy.test")
    with user_context(uid):
        mid = insert_medicine({"name": "Y", "frequency": "once_daily", "times": ["09:00"]})["id"]
        set_medicine_expiry(mid, _d(10))
        assert get_medicine(mid)["expiry_date"] == _d(10)
        set_medicine_expiry(mid, "")            # clear
        assert get_medicine(mid)["expiry_date"] == ""
        with pytest.raises(ValueError):
            set_medicine_expiry(mid, "31/12/2026")   # bad format


def test_expiring_buckets(app):
    _, uid = _uid(app, "mexp4@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Expired", "frequency": "once_daily", "times": ["09:00"], "expiry_date": _d(-5)})
        insert_medicine({"name": "Soon", "frequency": "once_daily", "times": ["09:00"], "expiry_date": _d(20)})
        insert_medicine({"name": "Later", "frequency": "once_daily", "times": ["09:00"], "expiry_date": _d(400)})
        insert_medicine({"name": "NoDate", "frequency": "once_daily", "times": ["09:00"]})
        d = get_expiring_medicines(within_days=60)
    assert [m["name"] for m in d["expired"]] == ["Expired"]
    assert [m["name"] for m in d["soon"]] == ["Soon"]      # Later & NoDate excluded
    assert d["has_any"] is True


def test_expiry_owner_scoped(app):
    _, ouid = _uid(app, "mexp5@medeasy.test")
    with user_context(ouid):
        mid = insert_medicine({"name": "Z", "frequency": "once_daily", "times": ["09:00"]})["id"]
    _, other = _uid(app, "mexp6@medeasy.test")
    with user_context(other):
        with pytest.raises(ValueError):
            set_medicine_expiry(mid, _d(30))


def test_api(app):
    c, uid = _uid(app, "mexp7@medeasy.test")
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
    assert c.post(f"/api/medicines/{mid}/expiry", json={"expiry_date": _d(15)}).status_code == 200
    body = c.get("/api/medicines/expiring?days=60").get_json()
    assert body["has_any"] is True and body["soon"][0]["name"] == "Med"
