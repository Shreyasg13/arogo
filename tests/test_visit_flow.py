"""Per-appointment visit flow — before/during/after tied to one appointment.

Guards the linkage the feature adds: questions and action items belong to a
SPECIFIC visit (never leak into the global lists or across users), the provider
link only accepts an owned provider, and the detail payload is user-scoped.
"""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today
from db.health import create_appointment, add_doctor_question, list_doctor_questions
from db.providers import create_provider
from db.visit_flow import (get_visit_detail, add_visit_action, list_visit_actions,
                           toggle_visit_action, delete_visit_action, list_visit_questions)

PW = "visit-pw-12345"


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


def _future(days=3):
    return (dt.date.fromisoformat(user_today()) + dt.timedelta(days=days)).isoformat()


def _past(days=3):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=days)).isoformat()


# ── detail ownership ────────────────────────────────────────────────────────

def test_detail_none_for_unknown(app):
    _, uid = _uid(app, "vf1@medeasy.test")
    with user_context(uid):
        assert get_visit_detail("nope") is None


def test_detail_shape(app):
    _, uid = _uid(app, "vf2@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "GP", "kind": "doctor", "date": _future()})
        d = get_visit_detail(a["id"])
    assert d["appointment"]["title"] == "GP"
    assert d["is_past"] is False
    assert d["questions"] == [] and d["actions"] == []
    assert "bring" in d and set(d["bring"]) == {"refills", "labs_due"}
    # No internal columns leak.
    assert "user_id" not in d["appointment"] and "created_at" not in d["appointment"]


# ── per-visit questions vs the global list ──────────────────────────────────

def test_visit_questions_are_scoped_to_the_visit(app):
    _, uid = _uid(app, "vf3@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "Cardio", "kind": "doctor", "date": _future()})
        add_doctor_question("Global one")                      # goes to the general list
        add_doctor_question("Ask about statin", appointment_id=a["id"])   # pinned to this visit
        d = get_visit_detail(a["id"])
        globals_ = list_doctor_questions()
    vq = [q["question"] for q in d["questions"]]
    assert vq == ["Ask about statin"]                          # visit detail: only its own
    gq = [q["question"] for q in globals_]
    assert "Global one" in gq and "Ask about statin" not in gq  # global list: only NULL-linked


def test_add_question_to_foreign_appointment_rejected(app):
    _, a_uid = _uid(app, "vf4a@medeasy.test")
    _, b_uid = _uid(app, "vf4b@medeasy.test")
    with user_context(a_uid):
        appt = create_appointment({"title": "A's visit", "kind": "doctor", "date": _future()})
    with user_context(b_uid):
        with pytest.raises(ValueError):
            add_doctor_question("sneaky", appointment_id=appt["id"])


# ── action items ────────────────────────────────────────────────────────────

def test_action_items_crud_and_scope(app):
    _, uid = _uid(app, "vf5@medeasy.test")
    with user_context(uid):
        a = create_appointment({"title": "Ortho", "kind": "doctor", "date": _past()})
        it = add_visit_action(a["id"], "Book physio")
        assert list_visit_actions(a["id"])[0]["text"] == "Book physio"
        toggle_visit_action(it["id"])
        assert list_visit_actions(a["id"])[0]["done"] == 1
        d = get_visit_detail(a["id"])
        assert d["is_past"] is True and d["actions"][0]["done"] is True
        delete_visit_action(it["id"])
        assert list_visit_actions(a["id"]) == []


def test_action_on_foreign_appointment_rejected(app):
    _, a_uid = _uid(app, "vf6a@medeasy.test")
    _, b_uid = _uid(app, "vf6b@medeasy.test")
    with user_context(a_uid):
        appt = create_appointment({"title": "A's", "kind": "doctor", "date": _future()})
    with user_context(b_uid):
        with pytest.raises(ValueError):
            add_visit_action(appt["id"], "steal")


def test_isolation_detail(app):
    _, a_uid = _uid(app, "vf7a@medeasy.test")
    _, b_uid = _uid(app, "vf7b@medeasy.test")
    with user_context(a_uid):
        appt = create_appointment({"title": "Private", "kind": "doctor", "date": _future()})
    with user_context(b_uid):
        assert get_visit_detail(appt["id"]) is None      # B can't read A's visit


# ── provider link (revived, but only for an owned provider) ─────────────────

def test_provider_link_owned_only(app):
    _, uid = _uid(app, "vf8@medeasy.test")
    with user_context(uid):
        p = create_provider({"name": "Dr Rao", "specialty": "Cardiology"})
        good = create_appointment({"title": "Checkup", "kind": "doctor",
                                   "date": _future(), "provider_id": p["id"]})
        d = get_visit_detail(good["id"])
        assert d["provider"] and d["provider"]["name"] == "Dr Rao"
        # a bogus/foreign provider id is dropped to NULL, not stored
        bad = create_appointment({"title": "X", "kind": "doctor",
                                  "date": _future(), "provider_id": "nonexistent"})
        assert get_visit_detail(bad["id"])["provider"] is None


# ── route auth ──────────────────────────────────────────────────────────────

def test_detail_route_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/appointments/x/detail").status_code in (401, 403)


def test_detail_route_404_for_unknown(app):
    c, _ = _uid(app, "vf9@medeasy.test")
    assert c.get("/api/appointments/does-not-exist/detail").status_code == 404
