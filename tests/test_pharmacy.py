"""Default pharmacy — name + phone for one-tap refills, with a composed message."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.pharmacy import get_pharmacy, set_pharmacy, refill_message
from db.medicines import insert_medicine, update_medicine_stock

PW = "phar-pw-12345"


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


def test_default_empty(app):
    _, uid = _uid(app, "phar1@medeasy.test")
    with user_context(uid):
        p = get_pharmacy()
    assert p["has_pharmacy"] is False and p["name"] == "" and p["phone"] == ""


def test_set_and_sanitize_phone(app):
    _, uid = _uid(app, "phar2@medeasy.test")
    with user_context(uid):
        p = set_pharmacy("Apollo Pharmacy", "+91 98abc-765<script>0")
    assert p["name"] == "Apollo Pharmacy"
    # Only dialer-safe characters kept — no letters, no markup.
    assert "<" not in p["phone"] and "script" not in p["phone"]
    assert p["phone"] == "+91 98-7650"
    assert p["has_pharmacy"] is True


def test_refill_message_lists_low_meds(app):
    _, uid = _uid(app, "phar3@medeasy.test")
    with user_context(uid):
        for name in ("Metformin", "Losartan"):
            mid = insert_medicine({"name": name, "frequency": "once_daily", "times": ["09:00"]})["id"]
            update_medicine_stock(mid, pill_count=2, pills_per_dose=1, refill_threshold=7)  # low
        msg = refill_message()
    assert "Metformin" in msg and "Losartan" in msg and msg.startswith("Hi")


def test_refill_message_empty_when_nothing_low(app):
    _, uid = _uid(app, "phar4@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Well-stocked", "frequency": "once_daily", "times": ["09:00"]})
        assert refill_message() == ""


def test_api_round_trip(app):
    c, uid = _uid(app, "phar5@medeasy.test")
    assert c.post("/api/pharmacy", json={"name": "MedPlus", "phone": "044-1234"}).get_json()["pharmacy"]["name"] == "MedPlus"
    assert c.get("/api/pharmacy").get_json()["phone"] == "044-1234"
    # refill-list now carries the pharmacy + message
    body = c.get("/api/medicines/refill-list").get_json()
    assert "pharmacy" in body and "refill_message" in body
