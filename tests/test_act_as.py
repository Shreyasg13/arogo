"""Caregiver 'manage a family member on one device' (acting-as).

The whole point of this feature is a narrow, re-verified impersonation, so the
security boundary is what these tests pin down:

  - a caregiver can only act-as a member who granted allow_manage (else 403)
  - while acting-as, HEALTH data (meds, etc.) scopes to the managed member
  - while acting-as, ACCOUNT / AUTH / FAMILY stay the caregiver's own — so a
    caregiver can never touch the member's identity, account, or consent grants
  - revoking the grant takes effect immediately (next request falls back)
  - stopping returns the caregiver to their own data
"""
import re

import pytest

import auth as auth_module
import mailer
from app import create_app
from db.core import init_db, execute

PW = "actas-pw-12345"


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
    return _authed(app, "am-carol@medeasy.test")


@pytest.fixture(scope="module")
def dave(app, outbox):    # the member / patient being managed
    return _authed(app, "am-dave@medeasy.test")


@pytest.fixture(scope="module")
def eve(app, outbox):     # outsider, no group / no grant
    return _authed(app, "am-eve@medeasy.test")


def _invite_token(outbox, email):
    for m in reversed(outbox):
        if m["to"] == email:
            found = re.search(r"\?family_invite=(\S+)", m["text"])
            if found:
                return found.group(1)
    return None


@pytest.fixture(scope="module")
def group(carol, dave, outbox):
    carol.post("/api/family", json={"name": "Manage Family"})
    carol.post("/api/family/invite", json={"email": "am-dave@medeasy.test"})
    token = _invite_token(outbox, "am-dave@medeasy.test")
    assert token
    r = dave.post("/api/family/invite/accept", json={"token": token})
    assert r.status_code == 200
    return r.get_json()["group"]


def _uid(client, email):
    g = client.get("/api/family").get_json()["group"]
    return next(m["user_id"] for m in g["members"] if m["email"] == email)


class TestActAsBoundary:
    def test_blocked_without_grant(self, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        # Dave hasn't opted in — Carol can't manage him.
        r = carol.post("/api/family/act-as", json={"user_id": uid})
        assert r.status_code == 403
        # And he doesn't appear in her managed list.
        managed = carol.get("/api/family/acting-as").get_json()["managed"]
        assert all(m["user_id"] != uid for m in managed)

    def test_grant_makes_member_manageable(self, carol, dave, group):
        r = dave.post("/api/family/consent", json={"allow_manage": True})
        assert r.status_code == 200 and r.get_json()["consent"]["allow_manage"] is True
        uid = _uid(carol, "am-dave@medeasy.test")
        managed = carol.get("/api/family/acting-as").get_json()["managed"]
        assert any(m["user_id"] == uid for m in managed)

    def test_health_data_scopes_to_member(self, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        assert carol.post("/api/family/act-as", json={"user_id": uid}).status_code == 200

        # Carol adds a medicine *while managing Dave* → it's Dave's, not Carol's.
        r = carol.post("/api/medicines",
                       json={"name": "Dave-Metformin", "dosage": "500mg"})
        assert r.status_code == 200
        med_id = r.get_json()["medicine"]["id"]

        # It appears in Dave's own list...
        dave_meds = [m["name"] for m in dave.get("/api/medicines").get_json()]
        assert "Dave-Metformin" in dave_meds
        # ...and Carol's acting-as view shows it too (she's scoped to Dave).
        acting_meds = [m["name"] for m in carol.get("/api/medicines").get_json()]
        assert "Dave-Metformin" in acting_meds

        # Clean up so later assertions about Carol's own meds stay clean.
        carol.delete(f"/api/medicines/{med_id}")

    def test_account_and_auth_stay_caregivers(self, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        carol.post("/api/family/act-as", json={"user_id": uid})
        # /auth/me is on an excluded path → still reports Carol, never Dave.
        me = carol.get("/auth/me").get_json()
        assert me["email"] == "am-carol@medeasy.test"
        # /api/family also excluded → her own membership, and she still sees
        # herself as owner (not Dave).
        g = carol.get("/api/family").get_json()["group"]
        assert any(m["email"] == "am-carol@medeasy.test" for m in g["members"])

    def test_acting_as_reported(self, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        carol.post("/api/family/act-as", json={"user_id": uid})
        state = carol.get("/api/family/acting-as").get_json()
        assert state["acting_as"] == uid

    def test_revoking_grant_takes_effect_immediately(self, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        carol.post("/api/family/act-as", json={"user_id": uid})
        # Dave revokes mid-session. Carol's session still says acting_as, but the
        # grant is re-checked every request, so her data falls back to her own.
        dave.post("/api/family/consent", json={"allow_manage": False})
        my_meds = [m["name"] for m in carol.get("/api/medicines").get_json()]
        assert "Dave-Metformin" not in my_meds
        # Re-grant for the remaining tests.
        dave.post("/api/family/consent", json={"allow_manage": True})

    def test_outsider_cannot_act_as(self, eve, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        r = eve.post("/api/family/act-as", json={"user_id": uid})
        assert r.status_code == 403

    def test_stop_returns_to_own_account(self, carol, dave, group):
        uid = _uid(carol, "am-dave@medeasy.test")
        carol.post("/api/family/act-as", json={"user_id": uid})
        assert carol.post("/api/family/act-as/stop").status_code == 200
        state = carol.get("/api/family/acting-as").get_json()
        assert state["acting_as"] is None


class TestPrivateCategoriesWalledFromManaging:
    """Managing a member's meds/health must NOT expose their private 'diary'
    categories — journal, mood, and cycle. This is what makes the private tab
    trustworthy for a young user whose parent set up (and can manage) their phone."""

    def _start(self, carol, dave):
        # Ensure the grant is live, then switch into managing Dave.
        dave.post("/api/family/consent", json={"allow_manage": True})
        uid = _uid(carol, "am-dave@medeasy.test")
        carol.post("/api/family/act-as", json={"user_id": uid})
        return uid

    def test_journal_blocked_while_managing(self, carol, dave, group):
        self._start(carol, dave)
        r = carol.get("/api/thoughts")
        assert r.status_code == 403
        assert r.get_json().get("code") == "PRIVATE_WHILE_ACTING"
        carol.post("/api/family/act-as/stop")

    def test_cycle_blocked_while_managing(self, carol, dave, group):
        self._start(carol, dave)
        assert carol.get("/api/cycle").status_code == 403
        carol.post("/api/family/act-as/stop")

    def test_mood_correlation_blocked_while_managing(self, carol, dave, group):
        self._start(carol, dave)
        assert carol.get("/api/mood-sleep/correlation").status_code == 403
        carol.post("/api/family/act-as/stop")

    def test_menopause_and_pregnancy_blocked_while_managing(self, carol, dave, group):
        # Review finding: menopause + pregnancy are as intimate as cycle — a
        # caregiver managing a member's meds must not read them either.
        self._start(carol, dave)
        assert carol.get("/api/menopause").status_code == 403
        assert carol.get("/api/pregnancy").status_code == 403
        assert carol.get("/api/pregnancy").get_json().get("code") == "PRIVATE_WHILE_ACTING"
        carol.post("/api/family/act-as/stop")

    def test_member_still_sees_own_private_data(self, carol, dave, group):
        # The wall is only for the caregiver-while-managing; Dave's own access is fine.
        assert dave.get("/api/thoughts").status_code == 200
        assert dave.get("/api/cycle").status_code == 200

    def test_caregiver_sees_own_journal_when_not_managing(self, carol, dave, group):
        # Not managing → Carol's own private tabs work normally.
        carol.post("/api/family/act-as/stop")
        assert carol.get("/api/thoughts").status_code == 200

    def test_meds_still_manageable_while_journal_walled(self, carol, dave, group):
        # The wall is surgical: meds/health management still works, only the
        # diary categories are off-limits.
        self._start(carol, dave)
        assert carol.get("/api/medicines").status_code == 200
        assert carol.get("/api/thoughts").status_code == 403
        carol.post("/api/family/act-as/stop")

    def test_v1_alias_cannot_bypass_the_private_wall(self, carol, dave, group):
        # Every /api/* route is also served at /api/v1/*. The wall matches
        # canonical prefixes, so the v1 alias must be normalized first — otherwise
        # /api/v1/thoughts would read the member's journal straight through.
        self._start(carol, dave)
        assert carol.get("/api/v1/thoughts").status_code == 403
        assert carol.get("/api/v1/thoughts/2026-08-01").status_code == 403
        assert carol.get("/api/v1/cycle").status_code == 403
        assert carol.get("/api/v1/mood-sleep/correlation").status_code == 403
        carol.post("/api/family/act-as/stop")

    def test_v1_alias_cannot_bypass_account_exclusion(self, carol, dave, group):
        # The account/family/auth exclusion must also survive the v1 alias — a
        # caregiver-acting-as must never export the MEMBER's data dump via
        # /api/v1/account/export. It must scope to the caregiver's own account.
        self._start(carol, dave)
        r = carol.get("/api/v1/account/export")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "am-carol@medeasy.test" in body        # the caregiver's own export
        assert "am-dave@medeasy.test" not in body      # NOT the managed member's
        carol.post("/api/family/act-as/stop")

    def test_portability_and_search_walled_while_managing(self, carol, dave, group):
        # /api/backup and /api/export dump the diary tables; /api/search returns
        # journal content (q="last week" returns ALL of it); /api/import would
        # overwrite the member's private data. None may run while acting-as —
        # canonical AND v1 paths — or they re-expose the walled categories.
        self._start(carol, dave)
        for path in ("/api/backup", "/api/export", "/api/export/counts",
                     "/api/search?q=last week", "/api/v1/backup",
                     "/api/v1/export", "/api/v1/search?q=a"):
            assert carol.get(path).status_code == 403, f"{path} must be walled"
        assert carol.post("/api/import", json={}).status_code == 403
        assert carol.post("/api/v1/import", json={}).status_code == 403
        # But ordinary meds/health management is untouched.
        assert carol.get("/api/medicines").status_code == 200
        carol.post("/api/family/act-as/stop")

    def test_caregiver_can_export_own_data_when_not_managing(self, carol, dave, group):
        # The wall is only while acting-as — the caregiver's own backup works.
        carol.post("/api/family/act-as/stop")
        assert carol.get("/api/backup").status_code == 200

    def test_pcos_dashboard_does_not_leak_cycle_while_managing(self, carol, dave, group):
        # The PCOS condition dashboard pulls cycle data. /api/conditions isn't a
        # walled prefix (a caregiver SHOULD see labs/meds), so the cycle block
        # itself must be withheld while acting-as — else it re-exposes the very
        # cycle data /api/cycle already blocks.
        uid = _uid(carol, "am-dave@medeasy.test")
        dave.post("/api/cycle/start", json={"start_date": "2026-06-01"})
        dave.post("/api/cycle/start", json={"start_date": "2026-07-05"})
        # Dave's own view includes the cycle block.
        assert dave.get("/api/conditions/pcos").get_json().get("cycle") is not None
        # Carol managing Dave: labs/meds visible, cycle withheld.
        dave.post("/api/family/consent", json={"allow_manage": True})
        carol.post("/api/family/act-as", json={"user_id": uid})
        pcos = carol.get("/api/conditions/pcos").get_json()
        assert pcos["cycle"] is None and pcos.get("cycle_private") is True
        assert "labs" in pcos          # meds/labs management still works
        carol.post("/api/family/act-as/stop")
