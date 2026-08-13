"""J6 — post-visit notes. Capture what the doctor said + follow-ups on a past
appointment. Own free text; only overwritten when explicitly supplied."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import create_appointment, update_appointment, list_appointments

PW = "vn-pw-1234567"


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


def test_visit_notes_saved_and_returned(app):
    _, uid = _uid(app, "vn1@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "Cardiology", "date": "2026-07-01"})
        assert a["visit_summary"] == "" and a["follow_up"] == ""
        up = update_appointment(a["id"], {"visit_summary": "BP a bit high, increased dose",
                                          "follow_up": "Recheck BP in 2 weeks"})
        assert up["visit_summary"] == "BP a bit high, increased dose"
        assert up["follow_up"] == "Recheck BP in 2 weeks"
        # persisted
        got = [x for x in list_appointments() if x["id"] == a["id"]][0]
        assert got["visit_summary"].startswith("BP a bit high")


def test_editing_other_fields_preserves_visit_notes(app):
    _, uid = _uid(app, "vn2@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "GP", "date": "2026-07-01"})
        update_appointment(a["id"], {"visit_summary": "All good", "follow_up": "None"})
        # Now edit an unrelated field WITHOUT sending the visit fields.
        up = update_appointment(a["id"], {"title": "GP (updated)"})
        assert up["title"] == "GP (updated)"
        assert up["visit_summary"] == "All good"      # not wiped
        assert up["follow_up"] == "None"


def test_api_patch(app):
    c, uid = _uid(app, "vn3@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "Derm", "date": "2026-07-01"})
    r = c.patch(f"/api/appointments/{a['id']}",
                json={"visit_summary": "Cream prescribed", "follow_up": "Photo in a month"})
    assert r.get_json()["success"] is True
    got = c.get("/api/appointments").get_json()["appointments"]
    row = [x for x in got if x["id"] == a["id"]][0]
    assert row["visit_summary"] == "Cream prescribed" and row["follow_up"] == "Photo in a month"


def test_visit_notes_owner_scoped(app):
    _, ouid = _uid(app, "vn4@medeasy.test")
    with user_context(ouid):
        a = create_appointment({"title": "Ortho", "date": "2026-07-01"})
    _, other = _uid(app, "vn5@medeasy.test")
    with user_context(other):
        with pytest.raises(ValueError):
            update_appointment(a["id"], {"visit_summary": "hijack"})
