"""J5 — "is it working?" effectiveness log. A periodic 1-5 self-rating per
medicine, with a trend. Owner-scoped; purely self-report, not a clinical measure."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import insert_medicine
from db.med_effectiveness import log_effectiveness, get_effectiveness

PW = "eff-pw-123456"


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


def _med(uid, name="Sertraline"):
    with user_context(uid):
        return insert_medicine({"name": name, "frequency": "once_daily", "times": ["09:00"]})["id"]


def test_rating_range_enforced(app):
    _, uid = _uid(app, "eff1@medeasy.test")
    mid = _med(uid)
    with user_context(uid):
        for bad in (0, 6, "x", None):
            with pytest.raises(ValueError):
                log_effectiveness({"medicine_id": mid, "rating": bad})


def test_average_and_direction(app):
    _, uid = _uid(app, "eff2@medeasy.test")
    mid = _med(uid)
    with user_context(uid):
        log_effectiveness({"medicine_id": mid, "rating": 2, "date_key": "2026-07-01"})
        log_effectiveness({"medicine_id": mid, "rating": 3, "date_key": "2026-07-15"})
        log_effectiveness({"medicine_id": mid, "rating": 5, "date_key": "2026-08-01"})
        d = get_effectiveness(days=3650)
    m = d["meds"][0]
    assert m["latest"] == 5 and m["count"] == 3
    assert m["average"] == round((2 + 3 + 5) / 3, 1)
    assert m["direction"] == "up"          # latest 5 well above prior mean 2.5


def test_downward_direction(app):
    _, uid = _uid(app, "eff3@medeasy.test")
    mid = _med(uid)
    with user_context(uid):
        log_effectiveness({"medicine_id": mid, "rating": 5, "date_key": "2026-07-01"})
        log_effectiveness({"medicine_id": mid, "rating": 2, "date_key": "2026-08-01"})
        d = get_effectiveness(days=3650)
    assert d["meds"][0]["direction"] == "down"


def test_cannot_rate_foreign_medicine(app):
    _, ouid = _uid(app, "eff4@medeasy.test")
    mid = _med(ouid)
    _, other = _uid(app, "eff5@medeasy.test")
    with user_context(other):
        with pytest.raises(ValueError):
            log_effectiveness({"medicine_id": mid, "rating": 4})


def test_api_roundtrip(app):
    c, uid = _uid(app, "eff6@medeasy.test")
    mid = _med(uid)
    r = c.post("/api/medicines/effectiveness", json={"medicine_id": mid, "rating": 4})
    assert r.get_json()["success"] is True
    body = c.get("/api/medicines/effectiveness").get_json()
    assert body["has_data"] is True and body["meds"][0]["latest"] == 4
    rid = body["meds"][0]["series"][0]["id"]
    assert c.delete(f"/api/medicines/effectiveness/{rid}").status_code == 200
    assert c.get("/api/medicines/effectiveness").get_json()["has_data"] is False
