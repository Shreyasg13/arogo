"""
tests/test_family.py — Phase 3 family sharing / consent model.

Cast: Carol (group owner), Dave (invited member), Eve (outsider).
Verifies the consent model end to end: nothing is shared by default,
categories appear only after opt-in, outsiders get 403, invites are
email-bound and revocable.

Run:  pytest tests/test_family.py -v
"""
import os
os.environ["MEDEASY_DB"] = ":memory:"

import datetime
import re
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
import auth as auth_module
import mailer
from db.core import init_db
from app import create_app

TODAY = datetime.date.today().isoformat()
PW = "family-pw-12345"


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
    """Module-wide email capture (monkeypatch is function-scoped, so patch manually)."""
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
def carol(app, outbox):
    return _authed(app, "carol@medeasy.test")


@pytest.fixture(scope="module")
def dave(app, outbox):
    return _authed(app, "dave@medeasy.test")


@pytest.fixture(scope="module")
def eve(app, outbox):
    return _authed(app, "eve@medeasy.test")


def _invite_token(outbox, email):
    for m in reversed(outbox):
        if m["to"] == email:
            found = re.search(r"\?family_invite=(\S+)", m["text"])
            if found:
                return found.group(1)
    return None


@pytest.fixture(scope="module")
def group(carol, dave, outbox):
    """Carol creates a group and Dave accepts an invite."""
    r = carol.post("/api/family", json={"name": "Test Family"})
    assert r.status_code == 200 and r.get_json()["success"]
    r = carol.post("/api/family/invite", json={"email": "dave@medeasy.test"})
    assert r.status_code == 200
    token = _invite_token(outbox, "dave@medeasy.test")
    assert token, "no invite email captured"
    r = dave.post("/api/family/invite/accept", json={"token": token})
    assert r.status_code == 200 and r.get_json()["success"]
    return r.get_json()["group"]


class TestGroupLifecycle:
    def test_group_has_both_members(self, carol, group):
        g = carol.get("/api/family").get_json()["group"]
        emails = {m["email"] for m in g["members"]}
        assert emails == {"carol@medeasy.test", "dave@medeasy.test"}
        assert g["my_role"] == "owner"

    def test_cannot_create_second_group(self, dave, group):
        assert dave.post("/api/family", json={"name": "Another"}).status_code == 400

    def test_owner_cannot_leave(self, carol, group):
        assert carol.post("/api/family/leave").status_code == 400


class TestInviteRules:
    def test_member_cannot_invite(self, dave, group):
        r = dave.post("/api/family/invite", json={"email": "eve@medeasy.test"})
        assert r.status_code == 400

    def test_invite_is_email_bound(self, carol, eve, group, outbox):
        # Carol invites frank@, Eve (different email) tries to hijack the token
        carol.post("/api/family/invite", json={"email": "frank@medeasy.test"})
        token = _invite_token(outbox, "frank@medeasy.test")
        assert token
        r = eve.post("/api/family/invite/accept", json={"token": token})
        assert r.status_code == 400
        assert "different email" in r.get_json()["error"]

    def test_revoked_invite_cannot_be_accepted(self, app, carol, group, outbox):
        carol.post("/api/family/invite", json={"email": "grace@medeasy.test"})
        token = _invite_token(outbox, "grace@medeasy.test")
        g = carol.get("/api/family").get_json()["group"]
        iid = next(i["id"] for i in g["pending_invites"]
                   if i["email"] == "grace@medeasy.test")
        assert carol.delete(f"/api/family/invite/{iid}").status_code == 200

        grace = _authed(app, "grace@medeasy.test")
        r = grace.post("/api/family/invite/accept", json={"token": token})
        assert r.status_code == 400

    def test_garbage_token_rejected(self, dave, group):
        r = dave.post("/api/family/invite/accept", json={"token": "garbage"})
        assert r.status_code == 400


class TestConsent:
    def test_nothing_shared_by_default(self, carol, dave, group):
        dave_id = next(m["user_id"] for m in group["members"]
                       if m["email"] == "dave@medeasy.test")
        s = carol.get(f"/api/family/member/{dave_id}/summary").get_json()
        assert all(not v for v in s["shares"].values())
        for cat in ["sleep", "vitals", "medicines", "food", "symptoms"]:
            assert cat not in s, f"{cat} leaked without consent"

    def test_shared_category_appears_after_opt_in(self, carol, dave, group):
        dave.post("/api/sleep", json={
            "bedtime": f"{TODAY}T23:30", "wake_time": f"{TODAY}T07:00",
            "date_key": TODAY, "quality": 4})
        dave.post("/api/vitals", json={"type": "heart_rate", "value1": 58,
                                       "date_key": TODAY})
        r = dave.post("/api/family/consent", json={"share_sleep": True})
        assert r.get_json()["consent"]["share_sleep"] is True

        dave_id = next(m["user_id"] for m in group["members"]
                       if m["email"] == "dave@medeasy.test")
        s = carol.get(f"/api/family/member/{dave_id}/summary").get_json()
        assert "sleep" in s and s["sleep"]["nights"] >= 1
        # vitals still off
        assert "vitals" not in s

    def test_consent_can_be_withdrawn(self, carol, dave, group):
        dave.post("/api/family/consent", json={"share_sleep": False})
        dave_id = next(m["user_id"] for m in group["members"]
                       if m["email"] == "dave@medeasy.test")
        s = carol.get(f"/api/family/member/{dave_id}/summary").get_json()
        assert "sleep" not in s

    def test_outsider_gets_403(self, eve, group):
        carol_id = next(m["user_id"] for m in group["members"]
                        if m["email"] == "carol@medeasy.test")
        assert eve.get(f"/api/family/member/{carol_id}/summary").status_code == 403

    def test_unauthenticated_gets_401(self, app, group):
        anon = app.test_client()
        assert anon.get("/api/family").status_code == 401


class TestCaregiverAlerts:
    def test_alerts_require_medicine_sharing(self, dave, group):
        r = dave.post("/api/family/consent", json={"alert_missed_doses": True})
        assert r.status_code == 400
        assert "medicine sharing" in r.get_json()["error"]

    def test_overdue_dose_alerts_family_once(self, app, carol, dave, group, monkeypatch):
        import datetime as dt
        import push as push_module
        import mailer
        import scheduler

        # Dave shares medicines and opts in to alerts
        r = dave.post("/api/family/consent",
                      json={"share_medicines": True, "alert_missed_doses": True})
        assert r.get_json()["consent"]["alert_missed_doses"] is True

        # A dose scheduled at 09:00, "now" mocked to noon → 3h overdue
        r = dave.post("/api/medicines", json={
            "name": "AlertPill", "dosage": "10", "times": ["09:00"]})
        assert r.status_code == 200
        noon = dt.datetime.combine(dt.date.today(), dt.time(12, 0))
        monkeypatch.setattr(scheduler, "_user_local_now", lambda uid: noon)

        pushes, mails = [], []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, t, b, url='/': pushes.append({"uid": uid, "title": t}) or 1)
        monkeypatch.setattr(mailer, "send_email",
                            lambda to, s, txt: mails.append({"to": to, "subject": s}) or True)

        scheduler._caregiver_alerts()

        carol_id = next(m["user_id"] for m in group["members"]
                        if m["email"] == "carol@medeasy.test")
        dave_id = next(m["user_id"] for m in group["members"]
                       if m["email"] == "dave@medeasy.test")
        alert_pushes = [p for p in pushes if "missed a dose" in p["title"]]
        assert any(p["uid"] == carol_id for p in alert_pushes), "Carol wasn't alerted"
        assert not any(p["uid"] == dave_id for p in alert_pushes), \
            "the watched member shouldn't be alerted about themselves"
        assert any(m["to"] == "carol@medeasy.test" for m in mails)

        # Second run within the same day: deduped
        pushes.clear(); mails.clear()
        scheduler._caregiver_alerts()
        assert not pushes and not mails

    def test_self_correct_nudge_before_family_is_told(self, app, dave, group, monkeypatch):
        # 90 min overdue → only the MEMBER is nudged; family is NOT alerted yet.
        import datetime as dt
        import push as push_module
        import mailer
        import scheduler

        dave.post("/api/family/consent",
                  json={"share_medicines": True, "alert_missed_doses": True})
        r = dave.post("/api/medicines", json={
            "name": "SelfNudgePill", "dosage": "1", "times": ["09:00"]})
        assert r.status_code == 200

        # "now" = 10:30 → 90 min overdue (between self-correct 60 and escalate 120)
        t1030 = dt.datetime.combine(dt.date.today(), dt.time(10, 30))
        monkeypatch.setattr(scheduler, "_user_local_now", lambda uid: t1030)

        pushes, mails = [], []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, t, b, url='/': pushes.append({"uid": uid, "title": t}) or 1)
        monkeypatch.setattr(mailer, "send_email",
                            lambda to, s, txt: mails.append(to) or True)

        scheduler._caregiver_alerts()

        dave_id = next(m["user_id"] for m in group["members"]
                       if m["email"] == "dave@medeasy.test")
        # The member got a self-correct nudge…
        assert any(p["uid"] == dave_id and "Don't forget" in p["title"] for p in pushes)
        # …and NOBODY was told they "missed a dose" yet, no emails sent.
        assert not any("missed a dose" in p["title"] for p in pushes)
        assert not mails

    def test_member_told_when_family_is_alerted(self, app, dave, group, monkeypatch):
        # 3h overdue → family alerted AND the member is told (transparency).
        import datetime as dt
        import push as push_module
        import mailer
        import scheduler

        dave.post("/api/family/consent",
                  json={"share_medicines": True, "alert_missed_doses": True})
        r = dave.post("/api/medicines", json={
            "name": "TransparencyPill", "dosage": "1", "times": ["09:00"]})
        assert r.status_code == 200
        noon = dt.datetime.combine(dt.date.today(), dt.time(12, 0))
        monkeypatch.setattr(scheduler, "_user_local_now", lambda uid: noon)

        pushes = []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, t, b, url='/': pushes.append({"uid": uid, "title": t}) or 1)
        monkeypatch.setattr(mailer, "send_email", lambda to, s, txt: True)

        scheduler._caregiver_alerts()

        dave_id = next(m["user_id"] for m in group["members"]
                       if m["email"] == "dave@medeasy.test")
        # Member is told family was notified (never covert)
        assert any(p["uid"] == dave_id and "family" in p["title"].lower() for p in pushes)

    def test_taken_dose_never_alerts(self, app, dave, group, monkeypatch):
        import datetime as dt
        import push as push_module
        import scheduler

        r = dave.post("/api/medicines", json={
            "name": "TakenAlertPill", "dosage": "10", "times": ["08:00"]})
        mid = r.get_json()["medicine"]["id"]
        dave.post(f"/api/medicines/{mid}/log", json={"time": "08:00", "taken": True})

        noon = dt.datetime.combine(dt.date.today(), dt.time(12, 0))
        monkeypatch.setattr(scheduler, "_user_local_now", lambda uid: noon)
        pushes = []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, t, b, url='/': pushes.append(t) or 1)
        scheduler._caregiver_alerts()
        assert not [t for t in pushes if "TakenAlertPill" in t]

    def test_withdrawing_medicine_sharing_silences_alerts(self, dave, group):
        r = dave.post("/api/family/consent", json={"share_medicines": False})
        c = r.get_json()["consent"]
        assert c["share_medicines"] is False
        assert c["alert_missed_doses"] is False


class TestCareStatus:
    """Dashboard caregiver panel: /api/family/care-status shows today's dose
    status of members who share their medicines — and only them."""

    def _dave_id(self, group):
        return next(m["user_id"] for m in group["members"]
                    if m["email"] == "dave@medeasy.test")

    def test_lists_member_sharing_medicines(self, carol, dave, group):
        dave.post("/api/family/consent", json={"share_medicines": True})
        r = dave.post("/api/medicines", json={
            "name": "CarePill", "dosage": "5", "times": ["08:00", "20:00"]})
        mid = r.get_json()["medicine"]["id"]
        dave.post(f"/api/medicines/{mid}/log", json={"time": "08:00", "taken": True})

        status = carol.get("/api/family/care-status").get_json()
        row = next((m for m in status if m["user_id"] == self._dave_id(group)), None)
        assert row is not None, "sharing member missing from care-status"
        assert row["total"] >= 2 and row["taken"] >= 1
        assert isinstance(row["overdue"], list)

    def test_excludes_member_not_sharing_medicines(self, carol, dave, group):
        dave.post("/api/family/consent", json={"share_medicines": False})
        status = carol.get("/api/family/care-status").get_json()
        assert all(m["user_id"] != self._dave_id(group) for m in status)

    def test_excludes_self(self, carol, group):
        carol_id = next(m["user_id"] for m in group["members"]
                        if m["email"] == "carol@medeasy.test")
        status = carol.get("/api/family/care-status").get_json()
        assert all(m["user_id"] != carol_id for m in status)

    def test_outsider_sees_empty(self, eve):
        assert eve.get("/api/family/care-status").get_json() == []

    def test_care_ack_marks_checking(self, carol, dave, group):
        dave.post("/api/family/consent", json={"share_medicines": True})
        dave_id = self._dave_id(group)
        r = carol.post("/api/family/care-ack", json={"target_user_id": dave_id})
        assert r.status_code == 200
        row = next(m for m in carol.get("/api/family/care-status").get_json()
                   if m["user_id"] == dave_id)
        assert row["checking_is_me"] is True
        assert row["checking_by"]   # Carol's name/email recorded

    def test_care_ack_rejects_non_group_member(self, carol, group):
        r = carol.post("/api/family/care-ack", json={"target_user_id": "nobody"})
        assert r.status_code == 403


class TestMemberManagement:
    def test_member_cannot_remove_others(self, dave, group):
        carol_id = next(m["user_id"] for m in group["members"]
                        if m["email"] == "carol@medeasy.test")
        assert dave.delete(f"/api/family/member/{carol_id}").status_code == 400

    def test_delete_group_blocked_while_members_remain(self, carol, group):
        assert carol.delete("/api/family").status_code == 400

    def test_member_can_leave_then_owner_deletes(self, carol, dave, group):
        assert dave.post("/api/family/leave").status_code == 200
        assert dave.get("/api/family").get_json()["group"] is None
        assert carol.delete("/api/family").status_code == 200
        assert carol.get("/api/family").get_json()["group"] is None
