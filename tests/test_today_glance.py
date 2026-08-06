"""Today-at-a-glance — a real, un-padded roll-up of what stands today."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.insights import get_today_glance
from db.medicines import insert_medicine, update_medicine_stock
from db.health import create_appointment, add_measurement_reminder, log_vital

PW = "glance-pw-12345"


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


def test_empty_when_nothing(app):
    _, uid = _uid(app, "tglance1@medeasy.test")
    with user_context(uid):
        g = get_today_glance()
    assert g["has_anything"] is False
    assert g["doses_left"] == 0 and g["next_appointment"] is None
    assert g["low_stock_count"] == 0 and g["measurements_due"] == []


def test_counts_doses_appt_and_low(app):
    _, uid = _uid(app, "tglance2@medeasy.test")
    with user_context(uid):
        insert_medicine({"name": "Metformin", "frequency": "twice_daily", "times": ["09:00", "21:00"]})
        low_id = insert_medicine({"name": "Losartan", "frequency": "once_daily", "times": ["08:00"]})["id"]
        update_medicine_stock(low_id, pill_count=1, pills_per_dose=1, refill_threshold=7)  # low
        create_appointment({"title": "GP", "kind": "doctor",
                            "date": (dt.date.today() + dt.timedelta(days=3)).isoformat()})
        g = get_today_glance()
    assert g["doses_left"] == 3            # 2 Metformin + 1 Losartan, none taken
    assert g["next_appointment"]["title"] == "GP"
    assert g["low_stock_count"] == 1
    assert g["has_anything"] is True


def test_measurement_due_clears_when_logged(app):
    _, uid = _uid(app, "tglance3@medeasy.test")
    with user_context(uid):
        add_measurement_reminder("blood_pressure", "08:00")
        assert "blood_pressure" in get_today_glance()["measurements_due"]
        log_vital({"type": "blood_pressure", "value1": 120, "value2": 80})   # logged today
        assert "blood_pressure" not in get_today_glance()["measurements_due"]


def test_api(app):
    c, uid = _uid(app, "tglance4@medeasy.test")
    body = c.get("/api/today/glance").get_json()
    assert "doses_left" in body and "has_anything" in body
