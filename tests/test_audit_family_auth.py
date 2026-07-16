"""
tests/test_audit_family_auth.py — Audit / stress-test suite for the
Family-sharing, Auth, Notifications, Reminder-settings and Data-export
surfaces of Arogo.

Written during a product+QA audit. Each test either:
  - pins CORRECT behaviour that the audit verified holds (regression guard), or
  - documents a REAL BUG found during the audit (marked `xfail` with a
    reason, so the suite stays green until the app code is fixed, then
    flips to XPASS to prove the fix).

Cast: Adam (owner), Beth (member), Carl (outsider).

Run:  pytest tests/test_audit_family_auth.py -v
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
from db.core import init_db, execute, new_id, now_iso
from app import create_app

TODAY = datetime.date.today().isoformat()
PW = "audit-pw-123456"


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    """Module-wide email capture (monkeypatch is function-scoped)."""
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


def _uid(email):
    row = execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True)
    return row["id"] if row else None


def _invite_token(outbox, email):
    for m in reversed(outbox):
        if m["to"] == email:
            found = re.search(r"\?family_invite=(\S+)", m["text"])
            if found:
                return found.group(1)
    return None


@pytest.fixture(scope="module")
def adam(app, outbox):
    return _authed(app, "adam@audit.test")


@pytest.fixture(scope="module")
def beth(app, outbox):
    return _authed(app, "beth@audit.test")


@pytest.fixture(scope="module")
def carl(app, outbox):
    return _authed(app, "carl@audit.test")


@pytest.fixture(scope="module")
def group(adam, beth, outbox):
    """Adam owns a group, Beth accepts an invite into it."""
    r = adam.post("/api/family", json={"name": "Audit Family"})
    assert r.status_code == 200
    adam.post("/api/family/invite", json={"email": "beth@audit.test"})
    token = _invite_token(outbox, "beth@audit.test")
    assert token
    r = beth.post("/api/family/invite/accept", json={"token": token})
    assert r.status_code == 200
    return r.get_json()["group"]


# ══════════════════════════════════════════════════════════════════════════════
# BUGS  (fixed — these now assert the corrected behaviour; regression guards)
# ══════════════════════════════════════════════════════════════════════════════

class TestBugs:

    def test_orphaned_membership_row_does_not_500(self, adam, group):
        """A membership row that points at a now-deleted user must not 500."""
        gid = execute(
            "SELECT group_id FROM family_members WHERE user_id=?",
            (_uid("adam@audit.test"),), fetchone=True)["group_id"]
        ghost = "ghost-" + new_id()
        execute("INSERT INTO family_members (id,group_id,user_id,role,joined_at) "
                "VALUES (?,?,?,'member',?)",
                (new_id(), gid, ghost, now_iso()), commit=True)
        try:
            r = adam.get(f"/api/family/member/{ghost}/summary")
            # A graceful outcome is 403/404, never a 500.
            assert r.status_code in (403, 404), \
                f"expected graceful status, got {r.status_code}"
        finally:
            execute("DELETE FROM family_members WHERE user_id=?", (ghost,), commit=True)

    def test_reminder_settings_garbage_number_no_500(self, app):
        c = _authed(app, "rem-garbage@audit.test")
        r = c.post("/api/reminders/settings", json={"water_interval_h": "notanumber"})
        assert r.status_code in (200, 400), f"got {r.status_code}"

    def test_reminder_time_fields_are_validated(self, app):
        c = _authed(app, "rem-time@audit.test")
        r = c.post("/api/reminders/settings",
                   json={"water_start": "garbage", "habit_reminder_time": "99:99"})
        settings = r.get_json()["settings"]
        # A validating endpoint would reject or normalise, never echo 'garbage'.
        assert settings["water_start"] != "garbage"
        assert settings["habit_reminder_time"] != "99:99"


# ══════════════════════════════════════════════════════════════════════════════
# FAMILY — invite / accept / consent edge cases (correct behaviour, regression)
# ══════════════════════════════════════════════════════════════════════════════

class TestFamilyInviteEdges:

    def test_invite_self_is_rejected(self, adam, group):
        r = adam.post("/api/family/invite", json={"email": "adam@audit.test"})
        assert r.status_code == 400
        # UX note in report: the message ("already in a family group") is
        # confusing for self-invite, but it IS rejected.

    def test_invite_existing_member_rejected(self, adam, group):
        r = adam.post("/api/family/invite", json={"email": "beth@audit.test"})
        assert r.status_code == 400
        assert "already in a family group" in r.get_json()["error"]

    def test_member_cannot_invite(self, beth, group):
        r = beth.post("/api/family/invite", json={"email": "carl@audit.test"})
        assert r.status_code == 400

    def test_invite_malformed_email_rejected(self, adam, group):
        r = adam.post("/api/family/invite", json={"email": "not-an-email"})
        assert r.status_code == 400
        assert "Valid email" in r.get_json()["error"]

    def test_invite_empty_email_rejected(self, adam, group):
        r = adam.post("/api/family/invite", json={"email": ""})
        assert r.status_code == 400

    def test_duplicate_pending_invite_rejected(self, adam, group, outbox):
        adam.post("/api/family/invite", json={"email": "hank@audit.test"})
        r = adam.post("/api/family/invite", json={"email": "hank@audit.test"})
        assert r.status_code == 400
        assert "already pending" in r.get_json()["error"]

    def test_accept_with_wrong_email_rejected(self, adam, carl, group, outbox):
        adam.post("/api/family/invite", json={"email": "iris@audit.test"})
        token = _invite_token(outbox, "iris@audit.test")
        assert token
        # Carl (different email) tries to redeem Iris's invite
        r = carl.post("/api/family/invite/accept", json={"token": token})
        assert r.status_code == 400
        assert "different email" in r.get_json()["error"]

    def test_accept_garbage_token_rejected(self, carl, group):
        r = carl.post("/api/family/invite/accept", json={"token": "not.a.token"})
        assert r.status_code == 400

    def test_accept_empty_token_rejected(self, carl, group):
        r = carl.post("/api/family/invite/accept", json={"token": ""})
        assert r.status_code == 400

    def test_revoke_nonexistent_invite_is_safe(self, adam, group):
        # Revoking a bogus id must not 500 — it's a silent no-op.
        r = adam.delete("/api/family/invite/does-not-exist")
        assert r.status_code == 200

    def test_revoked_invite_cannot_be_accepted(self, app, adam, group, outbox):
        adam.post("/api/family/invite", json={"email": "jane@audit.test"})
        token = _invite_token(outbox, "jane@audit.test")
        g = adam.get("/api/family").get_json()["group"]
        iid = next(i["id"] for i in g["pending_invites"]
                   if i["email"] == "jane@audit.test")
        assert adam.delete(f"/api/family/invite/{iid}").status_code == 200
        jane = _authed(app, "jane@audit.test")
        r = jane.post("/api/family/invite/accept", json={"token": token})
        assert r.status_code == 400


class TestFamilyConsentEdges:

    def test_bogus_consent_flags_ignored_not_500(self, adam, group):
        # Unknown keys should be silently ignored, never crash.
        r = adam.post("/api/family/consent",
                      json={"share_bogus": True, "drop_table": 1, "evil": "x"})
        assert r.status_code == 200
        # Only the real share flags + alert appear in the echoed consent.
        keys = set(r.get_json()["consent"].keys())
        assert keys == {"share_sleep", "share_vitals", "share_medicines",
                        "share_food", "share_symptoms", "share_emergency",
                        "alert_missed_doses"}

    def test_alert_without_medicine_sharing_rejected(self, beth, group):
        # Beth currently shares nothing; enabling alerts alone must fail.
        beth.post("/api/family/consent", json={"share_medicines": False})
        r = beth.post("/api/family/consent", json={"alert_missed_doses": True})
        assert r.status_code == 400
        assert "medicine sharing" in r.get_json()["error"]

    def test_withdrawing_meds_and_forcing_alert_same_call_rejected(self, beth, group):
        beth.post("/api/family/consent", json={"share_medicines": True})
        r = beth.post("/api/family/consent",
                      json={"share_medicines": False, "alert_missed_doses": True})
        assert r.status_code == 400

    def test_withdrawing_meds_silences_alert(self, beth, group):
        beth.post("/api/family/consent", json={"share_medicines": True})
        beth.post("/api/family/consent", json={"alert_missed_doses": True})
        r = beth.post("/api/family/consent", json={"share_medicines": False})
        c = r.get_json()["consent"]
        assert c["share_medicines"] is False
        assert c["alert_missed_doses"] is False

    def test_consent_update_outside_group_rejected(self, carl):
        # Carl is not in any group.
        r = carl.post("/api/family/consent", json={"share_sleep": True})
        assert r.status_code == 400
        assert "not in a family group" in r.get_json()["error"]


class TestFamilyPrivacy:

    def test_outsider_summary_403(self, carl, group):
        adam_id = _uid("adam@audit.test")
        r = carl.get(f"/api/family/member/{adam_id}/summary")
        assert r.status_code == 403

    def test_nonexistent_uid_summary_403(self, adam, group):
        r = adam.get("/api/family/member/totally-made-up/summary")
        assert r.status_code == 403

    def test_unshared_categories_never_leak(self, adam, beth, group):
        # Beth logs sleep + a vital but shares nothing.
        beth.post("/api/family/consent",
                  json={"share_sleep": False, "share_vitals": False})
        beth.post("/api/sleep", json={
            "bedtime": f"{TODAY}T23:00", "wake_time": f"{TODAY}T07:00",
            "date_key": TODAY, "quality": 4})
        beth.post("/api/vitals",
                  json={"type": "heart_rate", "value1": 60, "date_key": TODAY})
        beth_id = _uid("beth@audit.test")
        s = adam.get(f"/api/family/member/{beth_id}/summary").get_json()
        assert all(v is False for v in s["shares"].values())
        for cat in ("sleep", "vitals", "medicines", "food", "symptoms"):
            assert cat not in s, f"{cat} leaked without consent"

    def test_shared_sleep_appears_only_after_opt_in(self, adam, beth, group):
        beth.post("/api/family/consent", json={"share_sleep": True})
        beth_id = _uid("beth@audit.test")
        s = adam.get(f"/api/family/member/{beth_id}/summary").get_json()
        assert "sleep" in s
        assert "vitals" not in s
        # withdraw again
        beth.post("/api/family/consent", json={"share_sleep": False})
        s = adam.get(f"/api/family/member/{beth_id}/summary").get_json()
        assert "sleep" not in s


# ══════════════════════════════════════════════════════════════════════════════
# AUTH — register / login / verify / reset / resend
# ══════════════════════════════════════════════════════════════════════════════

class TestAuth:

    def test_duplicate_email_409(self, app):
        c = app.test_client()
        c.post("/auth/register", json={"email": "dup@audit.test", "password": PW})
        r = c.post("/auth/register", json={"email": "dup@audit.test", "password": PW})
        assert r.status_code == 409

    def test_duplicate_email_case_insensitive(self, app):
        c = app.test_client()
        c.post("/auth/register", json={"email": "MixedCase@audit.test", "password": PW})
        auth_module.reset_rate_limiter()
        r = c.post("/auth/register", json={"email": "mixedcase@audit.test", "password": PW})
        assert r.status_code == 409, "email uniqueness must be case-insensitive"

    def test_malformed_email_400(self, app):
        c = app.test_client()
        for bad in ("noatsign", "a@b", "@nolocal.com", "spaces in@x.com", ""):
            auth_module.reset_rate_limiter()
            r = c.post("/auth/register", json={"email": bad, "password": PW})
            assert r.status_code == 400, f"{bad!r} should be rejected"

    def test_weak_password_400(self, app):
        c = app.test_client()
        for weak in ("", "short", "1234567"):
            auth_module.reset_rate_limiter()
            r = c.post("/auth/register",
                       json={"email": f"weak-{len(weak)}@audit.test", "password": weak})
            assert r.status_code == 400
            assert "at least 8" in r.get_json()["error"]

    def test_overlong_password_400(self, app):
        c = app.test_client()
        r = c.post("/auth/register",
                   json={"email": "toolong@audit.test", "password": "x" * 200})
        assert r.status_code == 400

    def test_login_wrong_password_401_generic(self, app):
        c = app.test_client()
        c.post("/auth/register", json={"email": "li@audit.test", "password": PW})
        auth_module.reset_rate_limiter()
        r = c.post("/auth/login", json={"email": "li@audit.test", "password": "wrongpass1"})
        assert r.status_code == 401
        # Must NOT reveal whether the email exists.
        assert r.get_json()["error"] == "Incorrect email or password"

    def test_login_unknown_email_same_message(self, app):
        c = app.test_client()
        r = c.post("/auth/login",
                   json={"email": "nobody@audit.test", "password": "whatever12"})
        assert r.status_code == 401
        assert r.get_json()["error"] == "Incorrect email or password"

    def test_forgot_password_never_reveals_existence(self, app):
        c = app.test_client()
        c.post("/auth/register", json={"email": "known@audit.test", "password": PW})
        auth_module.reset_rate_limiter()
        r_known = c.post("/auth/forgot-password", json={"email": "known@audit.test"})
        auth_module.reset_rate_limiter()
        r_unknown = c.post("/auth/forgot-password", json={"email": "ghost@audit.test"})
        assert r_known.status_code == r_unknown.status_code == 200
        assert r_known.get_json()["message"] == r_unknown.get_json()["message"]

    def test_reset_token_single_use(self, app, outbox):
        c = _authed(app, "resetme@audit.test")
        auth_module.reset_rate_limiter()
        c.post("/auth/forgot-password", json={"email": "resetme@audit.test"})
        tok = None
        for m in reversed(outbox):
            if m["to"] == "resetme@audit.test":
                f = re.search(r"\?reset=(\S+)", m["text"])
                if f:
                    tok = f.group(1)
                    break
        assert tok
        auth_module.reset_rate_limiter()
        r1 = c.post("/auth/reset-password", json={"token": tok, "password": "brandnew123"})
        assert r1.status_code == 200
        auth_module.reset_rate_limiter()
        r2 = c.post("/auth/reset-password", json={"token": tok, "password": "another12345"})
        assert r2.status_code == 400, "reset token must not be replayable"

    def test_reset_bumps_sessions(self, app, outbox):
        """After reset the old session cookie must be invalidated."""
        c = _authed(app, "sess@audit.test")
        assert c.get("/auth/me").status_code == 200
        auth_module.reset_rate_limiter()
        c.post("/auth/forgot-password", json={"email": "sess@audit.test"})
        tok = None
        for m in reversed(outbox):
            if m["to"] == "sess@audit.test":
                f = re.search(r"\?reset=(\S+)", m["text"])
                if f:
                    tok = f.group(1)
                    break
        auth_module.reset_rate_limiter()
        c.post("/auth/reset-password", json={"token": tok, "password": "freshpw12345"})
        # The old cookie should now be rejected.
        assert c.get("/auth/me").status_code == 401

    def test_reset_garbage_token_400(self, app):
        c = app.test_client()
        r = c.post("/auth/reset-password",
                   json={"token": "garbage", "password": "validpass123"})
        assert r.status_code == 400

    def test_resend_when_already_verified(self, app):
        c = _authed(app, "verified@audit.test")
        execute("UPDATE users SET verified=1 WHERE email=?",
                ("verified@audit.test",), commit=True)
        auth_module.reset_rate_limiter()
        r = c.post("/auth/resend-verification")
        assert r.status_code == 200
        assert "already verified" in r.get_json()["message"]

    def test_verify_bad_token_redirects_failure(self, app):
        c = app.test_client()
        r = c.get("/auth/verify/not-a-real-token")
        assert r.status_code in (301, 302)
        assert "verified=0" in r.headers.get("Location", "")

    def test_protected_route_requires_auth(self, app):
        anon = app.test_client()
        assert anon.get("/api/family").status_code == 401
        assert anon.get("/api/notifications").status_code == 401
        assert anon.get("/api/export/counts").status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS — user scoping
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifications:

    def test_notifications_are_user_scoped(self, app):
        a = _authed(app, "notif-a@audit.test")
        b = _authed(app, "notif-b@audit.test")
        a.post("/api/notifications",
               json={"type": "system", "title": "A-secret", "body": "for A only"})
        b_list = b.get("/api/notifications").get_json()["notifications"]
        assert all(n["title"] != "A-secret" for n in b_list), \
            "notification leaked across users"
        a_list = a.get("/api/notifications").get_json()["notifications"]
        assert any(n["title"] == "A-secret" for n in a_list)

    def test_mark_read_is_user_scoped(self, app):
        a = _authed(app, "notif-c@audit.test")
        b = _authed(app, "notif-d@audit.test")
        n = a.post("/api/notifications",
                   json={"type": "system", "title": "C-note"}).get_json()["notification"]
        # B cannot mark A's notification read (no-op, no error, count unchanged).
        before = a.get("/api/notifications?unread=1").get_json()["unread"]
        b.post(f"/api/notifications/{n['id']}/read")
        after = a.get("/api/notifications?unread=1").get_json()["unread"]
        assert before == after, "cross-user mark-read must not affect owner"

    def test_unread_count_isolated(self, app):
        a = _authed(app, "notif-e@audit.test")
        a.post("/api/notifications", json={"type": "system", "title": "E1"})
        a.post("/api/notifications", json={"type": "system", "title": "E2"})
        data = a.get("/api/notifications").get_json()
        assert data["unread"] >= 2
        a.post("/api/notifications/read-all")
        assert a.get("/api/notifications").get_json()["unread"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT — user scoping + garbage tolerance
# ══════════════════════════════════════════════════════════════════════════════

class TestExport:

    def test_export_is_user_scoped(self, app):
        a = _authed(app, "exp-a@audit.test")
        b = _authed(app, "exp-b@audit.test")
        a.post("/api/symptoms", json={"name": "Audit-Headache", "severity": 3,
                                      "date_key": TODAY})
        b_export = b.get("/api/export?format=json").get_json()
        b_symptoms = b_export.get("symptoms", [])
        assert all(s.get("name") != "Audit-Headache" for s in b_symptoms), \
            "export leaked another user's symptom"

    def test_export_counts_user_scoped(self, app):
        a = _authed(app, "exp-c@audit.test")
        b = _authed(app, "exp-d@audit.test")
        a.post("/api/symptoms", json={"name": "MineOnly", "severity": 2,
                                      "date_key": TODAY})
        assert b.get("/api/export/counts").get_json()["symptoms"] == 0

    def test_export_garbage_format_falls_back_to_json(self, app):
        c = _authed(app, "exp-fmt@audit.test")
        r = c.get("/api/export?format=garbage")
        assert r.status_code == 200
        assert r.mimetype == "application/json"

    def test_export_garbage_sections_yields_empty(self, app):
        c = _authed(app, "exp-sec@audit.test")
        r = c.get("/api/export?sections=garbage,evil")
        assert r.status_code == 200
        body = r.get_json()
        # No real section keys, just metadata.
        assert body["_meta"]["total_records"] == 0

    def test_export_sections_sql_injection_safe(self, app):
        c = _authed(app, "exp-sqli@audit.test")
        r = c.get("/api/export?sections=food_logs';DROP TABLE users;--")
        assert r.status_code == 200
        # users table must still exist
        assert execute("SELECT COUNT(*) AS n FROM users", fetchone=True)["n"] > 0

    def test_export_reversed_range_no_crash(self, app):
        c = _authed(app, "exp-rev@audit.test")
        r = c.get("/api/export/counts?from=2099-01-01&to=2000-01-01")
        assert r.status_code == 200
        assert all(v == 0 for v in r.get_json().values())

    def test_export_csv_content_type(self, app):
        c = _authed(app, "exp-csv@audit.test")
        r = c.get("/api/export?format=csv")
        assert r.status_code == 200
        assert r.mimetype == "text/csv"
        assert "attachment" in r.headers.get("Content-Disposition", "")


# ══════════════════════════════════════════════════════════════════════════════
# REMINDER SETTINGS — defaults, round-trip, digest-flag preservation
# ══════════════════════════════════════════════════════════════════════════════

class TestReminderSettings:

    def test_defaults_created_on_first_get(self, app):
        c = _authed(app, "rem-def@audit.test")
        s = c.get("/api/reminders/settings").get_json()
        assert s["water_enabled"] == 1
        assert s["water_start"] == "08:00"
        assert s.get("weekly_digest_enabled", 1) == 1

    def test_digest_flag_preserved_when_omitted(self, app):
        """Saving settings without weekly_digest_enabled must NOT re-enable it
        (otherwise the unsubscribe link is defeated on the next settings save)."""
        c = _authed(app, "rem-digest@audit.test")
        c.get("/api/reminders/settings")  # create row
        # Turn digest off via the DB (simulating unsubscribe)
        execute("UPDATE reminder_settings SET weekly_digest_enabled=0 WHERE user_id=?",
                (_uid("rem-digest@audit.test"),), commit=True)
        # Now save unrelated settings without the digest flag
        r = c.post("/api/reminders/settings", json={"water_enabled": 0})
        assert r.get_json()["settings"]["weekly_digest_enabled"] == 0, \
            "digest opt-out was silently reversed by a normal settings save"

    def test_settings_roundtrip(self, app):
        c = _authed(app, "rem-rt@audit.test")
        c.post("/api/reminders/settings",
               json={"water_goal_ml": 3000, "habit_reminder_time": "19:30"})
        s = c.get("/api/reminders/settings").get_json()
        assert s["water_goal_ml"] == 3000
        assert s["habit_reminder_time"] == "19:30"

    def test_digest_unsubscribe_bad_token(self, app):
        c = app.test_client()
        r = c.get("/api/digest/unsubscribe/garbage-token")
        assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# CAREGIVER ALERTS (scheduler) — opt-in gating + dedupe
# ══════════════════════════════════════════════════════════════════════════════

class TestCaregiverAlerts:

    def test_no_alert_without_medicine_sharing(self, app, outbox, monkeypatch):
        """A member with alert_missed_doses forced on but share_medicines OFF
        must never trigger caregiver alerts (the scheduler filters on both)."""
        import datetime as dt
        import push as push_module
        import scheduler

        owner = _authed(app, "cg-owner@audit.test")
        member = _authed(app, "cg-member@audit.test")
        owner.post("/api/family", json={"name": "CG Family"})
        owner.post("/api/family/invite", json={"email": "cg-member@audit.test"})
        token = _invite_token(outbox, "cg-member@audit.test")
        member.post("/api/family/invite/accept", json={"token": token})

        # Force an inconsistent row: alerts on, medicines OFF (bypassing the
        # API guard, to prove the scheduler's own WHERE clause is the backstop).
        execute("UPDATE family_members SET alert_missed_doses=1, share_medicines=0 "
                "WHERE user_id=?", (_uid("cg-member@audit.test"),), commit=True)

        # Member has an overdue dose.
        member.post("/api/medicines",
                    json={"name": "GatePill", "dosage": "5", "times": ["08:00"]})
        noon = dt.datetime.combine(dt.date.today(), dt.time(12, 0))
        monkeypatch.setattr(scheduler, "_user_local_now", lambda uid: noon)
        pushes = []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, t, b, url='/': pushes.append(t) or 1)

        scheduler._caregiver_alerts()
        assert not [t for t in pushes if "GatePill" in t or "missed a dose" in t], \
            "caregiver alert fired despite medicine sharing being OFF"

    def test_overdue_dose_alerts_once_then_deduped(self, app, outbox, monkeypatch):
        import datetime as dt
        import push as push_module
        import mailer as mailer_mod
        import scheduler

        owner = _authed(app, "cg2-owner@audit.test")
        member = _authed(app, "cg2-member@audit.test")
        owner.post("/api/family", json={"name": "CG2"})
        owner.post("/api/family/invite", json={"email": "cg2-member@audit.test"})
        token = _invite_token(outbox, "cg2-member@audit.test")
        member.post("/api/family/invite/accept", json={"token": token})

        r = member.post("/api/family/consent",
                        json={"share_medicines": True, "alert_missed_doses": True})
        assert r.get_json()["consent"]["alert_missed_doses"] is True

        member.post("/api/medicines",
                    json={"name": "OverduePill", "dosage": "5", "times": ["09:00"]})
        noon = dt.datetime.combine(dt.date.today(), dt.time(12, 0))
        monkeypatch.setattr(scheduler, "_user_local_now", lambda uid: noon)

        pushes, mails = [], []
        monkeypatch.setattr(push_module, "push_to_user",
                            lambda uid, t, b, url='/': pushes.append({"uid": uid, "t": t}) or 1)
        monkeypatch.setattr(mailer_mod, "send_email",
                            lambda to, s, txt: mails.append(to) or True)

        scheduler._caregiver_alerts()
        owner_id = _uid("cg2-owner@audit.test")
        member_id = _uid("cg2-member@audit.test")
        alert_pushes = [p for p in pushes if "missed a dose" in p["t"]]
        assert any(p["uid"] == owner_id for p in alert_pushes), "owner not alerted"
        assert not any(p["uid"] == member_id for p in alert_pushes), \
            "member should not be alerted about themselves"

        # Second run same day → deduped.
        pushes.clear(); mails.clear()
        scheduler._caregiver_alerts()
        assert not pushes and not mails


# ══════════════════════════════════════════════════════════════════════════════
# PUSH — subscription scoping
# ══════════════════════════════════════════════════════════════════════════════

class TestPush:

    def test_subscribe_requires_valid_shape(self, app):
        c = _authed(app, "push-a@audit.test")
        r = c.post("/api/push/subscribe", json={"subscription": {"endpoint": "x"}})
        assert r.status_code == 400  # missing keys dict

    def test_unsubscribe_only_touches_own_row(self, app):
        a = _authed(app, "push-b@audit.test")
        b = _authed(app, "push-c@audit.test")
        sub = {"endpoint": "https://push.example/AAA",
               "keys": {"p256dh": "k", "auth": "a"}}
        a.post("/api/push/subscribe", json={"subscription": sub})
        # B tries to unsubscribe A's endpoint — must not remove A's row.
        b.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/AAA"})
        row = execute("SELECT user_id FROM push_subscriptions WHERE endpoint=?",
                      ("https://push.example/AAA",), fetchone=True)
        assert row is not None, "another user deleted my push subscription"
        assert row["user_id"] == _uid("push-b@audit.test")
