"""Entity-linked health notes — the user's own words, stored verbatim."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health_notes import (create_note, update_note, delete_note, get_note,
                             list_notes, notes_for)

PW = "note-pw-12345"


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


def test_body_required(app):
    _, uid = _uid(app, "note1@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_note({"body": "   "})


def test_stored_verbatim(app):
    _, uid = _uid(app, "note2@medeasy.test")
    text = "Switched to the generic — the branded one upset my stomach. Dr said it's fine."
    with user_context(uid):
        n = create_note({"body": text, "entity_type": "medicine",
                         "entity_id": "med-1", "entity_label": "Metformin"})
    assert n["body"] == text                 # never reworded or interpreted
    assert n["entity_type"] == "medicine" and n["entity_label"] == "Metformin"


def test_unknown_entity_type_falls_back_to_general(app):
    _, uid = _uid(app, "note3@medeasy.test")
    with user_context(uid):
        n = create_note({"body": "x", "entity_type": "nonsense"})
    assert n["entity_type"] == "general"


def test_notes_for_entity_and_filtering(app):
    _, uid = _uid(app, "note4@medeasy.test")
    with user_context(uid):
        create_note({"body": "about metformin", "entity_type": "medicine", "entity_id": "m1"})
        create_note({"body": "about losartan", "entity_type": "medicine", "entity_id": "m2"})
        create_note({"body": "general thought", "entity_type": "general"})
        m1 = notes_for("medicine", "m1")
        meds = list_notes(entity_type="medicine")
        found = list_notes(q="losartan")
    assert [n["body"] for n in m1] == ["about metformin"]
    assert len(meds) == 2
    assert [n["body"] for n in found] == ["about losartan"]


def test_pinned_first(app):
    _, uid = _uid(app, "note5@medeasy.test")
    with user_context(uid):
        create_note({"body": "ordinary"})
        create_note({"body": "important", "pinned": True})
        got = [n["body"] for n in list_notes()]
    assert got[0] == "important"


def test_update_delete_and_isolation(app):
    _, a = _uid(app, "note6a@medeasy.test")
    _, b = _uid(app, "note6b@medeasy.test")
    with user_context(a):
        n = create_note({"body": "mine"})
        n2 = update_note(n["id"], {"body": "edited", "pinned": True})
        assert n2["body"] == "edited" and n2["pinned"] == 1
    with user_context(b):
        assert get_note(n["id"]) is None          # B can't read A's note
        assert list_notes() == []
        with pytest.raises(ValueError):
            update_note(n["id"], {"body": "hack"})
    with user_context(a):
        delete_note(n["id"])
        assert get_note(n["id"]) is None


def test_notes_never_leak_into_a_share(app):
    """A shared snapshot is a curated allow-list — notes must not appear."""
    from db.shares import compile_snapshot
    _, uid = _uid(app, "note7@medeasy.test")
    with user_context(uid):
        create_note({"body": "PRIVATE-NOTE-MARKER"})
    d = compile_snapshot(uid, None, "summary")
    assert "PRIVATE-NOTE-MARKER" not in str(d)
    assert "notes" not in d


def test_routes(app):
    c, _ = _uid(app, "note8@medeasy.test")
    assert c.get("/api/notes").status_code == 200
    r = c.post("/api/notes", json={"body": "route note", "entity_type": "condition"}).get_json()
    assert r["success"]
    nid = r["note"]["id"]
    assert c.patch(f"/api/notes/{nid}", json={"pinned": True}).get_json()["success"]
    assert c.delete(f"/api/notes/{nid}").get_json()["success"]


def test_route_requires_auth(app):
    assert app.test_client().get("/api/notes").status_code in (401, 403)
