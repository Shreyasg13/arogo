"""Forward visit-prep checklist — get ready for the next doctor visit."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.insights import get_visit_checklist
from db.health import create_appointment, add_doctor_question
from db.medicines import insert_medicine, update_medicine_stock

PW = "vchk-pw-12345"


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
    _, uid = _uid(app, "vchk1@medeasy.test")
    with user_context(uid):
        d = get_visit_checklist()
    assert d["next_visit"] is None and d["has_items"] is False


def test_next_visit_and_questions(app):
    _, uid = _uid(app, "vchk2@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "Cardiology", "kind": "doctor",
                            "date": (dt.date.today() + dt.timedelta(days=5)).isoformat()})
        add_doctor_question("Ask about the new chest tightness")
        d = get_visit_checklist()
    assert d["next_visit"]["title"] == "Cardiology"
    assert "Ask about the new chest tightness" in d["questions"]
    assert d["has_items"] is True


def test_refills_included(app):
    _, uid = _uid(app, "vchk3@medeasy.test")
    with user_context(uid):
        mid = insert_medicine({"name": "Metformin", "frequency": "once_daily", "times": ["09:00"]})["id"]
        update_medicine_stock(mid, pill_count=1, pills_per_dose=1, refill_threshold=7)   # low
        d = get_visit_checklist()
    assert any(r["name"] == "Metformin" for r in d["refills"])


def test_past_appointment_is_not_next_visit(app):
    _, uid = _uid(app, "vchk4@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "Old visit", "kind": "doctor",
                            "date": (dt.date.today() - dt.timedelta(days=5)).isoformat()})
        d = get_visit_checklist()
    assert d["next_visit"] is None       # a past visit doesn't anchor a forward checklist


def test_api(app):
    c, uid = _uid(app, "vchk5@medeasy.test")
    body = c.get("/api/visit-checklist").get_json()
    assert "questions" in body and "refills" in body and "labs_due" in body
