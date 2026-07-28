"""Caregiver-sets-Simple-View for a consenting family member (Phase 2, part 2).

The one place the app writes another user's data, so the guarantees matter:
  - consent-gated: only if the member opted in via allow_family_display
  - same-group-only: outsiders get 403
  - only ui_mode is touched, never other profile data
  - the member is always notified
"""
import re

import pytest

import auth as auth_module
import mailer
from app import create_app
from db.core import init_db, execute

PW = "display-pw-12345"


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def outbox():
    box = []
    original = mailer.send_email
    mailer.send_email = lambda to, subject, text: box.append(
        {"to": to, "subject": subject, "text": text}) or True
    yield box
    mailer.send_email = original


def _authed(app, email):
    c = app.test_client()
    r = c.post("/auth/register", json={"email": email, "password": PW})
    if r.status_code == 409:
        r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code in (200, 201)
    return c


@pytest.fixture(scope="module")
def carol(app, outbox):   # caregiver / group owner
    return _authed(app, "d-carol@medeasy.test")


@pytest.fixture(scope="module")
def dave(app, outbox):    # the member / patient
    return _authed(app, "d-dave@medeasy.test")


@pytest.fixture(scope="module")
def eve(app, outbox):     # outsider, no group
    return _authed(app, "d-eve@medeasy.test")


def _invite_token(outbox, email):
    for m in reversed(outbox):
        if m["to"] == email:
            found = re.search(r"\?family_invite=(\S+)", m["text"])
            if found:
                return found.group(1)
    return None


@pytest.fixture(scope="module")
def group(carol, dave, outbox):
    carol.post("/api/family", json={"name": "Display Family"})
    carol.post("/api/family/invite", json={"email": "d-dave@medeasy.test"})
    token = _invite_token(outbox, "d-dave@medeasy.test")
    assert token
    r = dave.post("/api/family/invite/accept", json={"token": token})
    assert r.status_code == 200
    return r.get_json()["group"]


def _dave_uid(carol):
    g = carol.get("/api/family").get_json()["group"]
    return next(m["user_id"] for m in g["members"] if m["email"] == "d-dave@medeasy.test")


class TestCaregiverDisplayControl:
    def test_blocked_until_member_opts_in(self, carol, dave, group):
        uid = _dave_uid(carol)
        # Dave hasn't allowed it → Carol is refused, and nothing is written.
        r = carol.post(f"/api/family/member/{uid}/display", json={"ui_mode": "simple"})
        assert r.status_code == 403
        prof = dave.get("/api/food/profile").get_json()["profile"]
        assert (prof.get("ui_mode") or None) is None

    def test_member_opt_in_is_visible_to_caregiver(self, carol, dave, group):
        r = dave.post("/api/family/consent", json={"allow_family_display": True})
        assert r.status_code == 200 and r.get_json()["consent"]["allow_family_display"] is True
        g = carol.get("/api/family").get_json()["group"]
        dave_row = next(m for m in g["members"] if m["email"] == "d-dave@medeasy.test")
        assert dave_row["allows_display"] is True

    def test_caregiver_can_set_and_member_is_notified(self, carol, dave, group):
        uid = _dave_uid(carol)
        r = carol.post(f"/api/family/member/{uid}/display", json={"ui_mode": "simple"})
        assert r.status_code == 200 and r.get_json()["result"]["ui_mode"] == "simple"
        # Dave's own profile now reads simple.
        assert dave.get("/api/food/profile").get_json()["profile"]["ui_mode"] == "simple"
        # Dave got a transparency notification naming the caregiver.
        note = execute("""SELECT title, type FROM notification_log
                          WHERE user_id=? AND type='family_display'
                          ORDER BY created_at DESC LIMIT 1""", (uid,), fetchone=True)
        assert note and "Simple View" in note["title"]

    def test_only_ui_mode_is_written(self, carol, dave, group):
        uid = _dave_uid(carol)
        dave.post("/api/food/profile", json={"name": "Dave Patient", "age": 71})
        carol.post(f"/api/family/member/{uid}/display", json={"ui_mode": "standard"})
        prof = dave.get("/api/food/profile").get_json()["profile"]
        assert prof["name"] == "Dave Patient"      # untouched
        assert prof["age"] == 71                    # untouched
        assert prof["ui_mode"] == "standard"        # only this field changed

    def test_outsider_is_refused(self, eve, carol, dave, group):
        uid = _dave_uid(carol)
        r = eve.post(f"/api/family/member/{uid}/display", json={"ui_mode": "simple"})
        assert r.status_code == 403

    def test_cannot_target_self(self, carol, group):
        g = carol.get("/api/family").get_json()["group"]
        my_uid = next(m["user_id"] for m in g["members"] if m["email"] == "d-carol@medeasy.test")
        r = carol.post(f"/api/family/member/{my_uid}/display", json={"ui_mode": "simple"})
        assert r.status_code == 400

    def test_revoking_consent_blocks_again(self, carol, dave, group):
        uid = _dave_uid(carol)
        dave.post("/api/family/consent", json={"allow_family_display": False})
        r = carol.post(f"/api/family/member/{uid}/display", json={"ui_mode": "simple"})
        assert r.status_code == 403
