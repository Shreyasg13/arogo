"""Scheduler safety-net regressions from the reminder-loop audit.

Covers the failure modes that would silently stop a medication reminder or a
missed-dose escalation:
  * /healthz surfaces a dead scheduler (heartbeat liveness)
  * start_scheduler() reports disabled state (so the worker can fail loudly)
  * a missed-dose escalation that reaches NOBODY must not burn the dose —
    it has to retry until a human is actually reached.
"""
import datetime
import os

import pytest

import scheduler
from app import create_app
from db.core import init_db, execute, new_id, now_iso


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


# ── /healthz liveness ────────────────────────────────────────────────────────
def test_healthz_reports_scheduler_liveness(app):
    c = app.test_client()
    with app.app_context():
        execute("DELETE FROM app_config WHERE key='scheduler_last_run'", commit=True)
    # No heartbeat yet → scheduler is not ok, last_run is null
    d = c.get("/healthz").get_json()
    assert d["status"] == "ok"                      # web process answered
    assert d["scheduler"]["ok"] is False
    assert d["scheduler"]["last_run"] is None
    # Fresh heartbeat → ok
    with app.app_context():
        scheduler._heartbeat()
    d = c.get("/healthz").get_json()
    assert d["scheduler"]["ok"] is True
    assert d["scheduler"]["age_seconds"] is not None
    # A stale heartbeat → not ok (dead scheduler becomes visible)
    with app.app_context():
        old = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
        execute("DELETE FROM app_config WHERE key='scheduler_last_run'", commit=True)
        execute("INSERT INTO app_config (key,value) VALUES ('scheduler_last_run',?)",
                (old,), commit=True)
    d = c.get("/healthz").get_json()
    assert d["scheduler"]["ok"] is False


def test_start_scheduler_disabled_returns_false(app, monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    assert scheduler.start_scheduler() is False


# ── Escalation retry (the audit's F3) ────────────────────────────────────────
def _seed_watched_member(app):
    """A member who shares medicines and opted into missed-dose alerts, plus one
    caregiver in the same group who receives alerts. Whether that caregiver is
    actually *reached* depends on the delivery mock, not the data — which is
    exactly the retry behaviour under test."""
    gid = "grp-esc"
    with app.app_context():
        uid = new_id()
        execute("INSERT INTO users (id,email,password_hash,name,created_at,verified) "
                "VALUES (?,?,?,?,?,1)",
                (uid, f"watched_{uid[:6]}@medeasy.test", "x", "Grandma", now_iso()),
                commit=True)
        execute("INSERT INTO family_members "
                "(id,group_id,user_id,role,alert_missed_doses,share_medicines,"
                " receive_care_alerts,joined_at) VALUES (?,?,?,'member',1,1,1,?)",
                (new_id(), gid, uid, now_iso()), commit=True)
        # A caregiver in the same group. Not watched (doesn't share meds), but
        # opted to receive care alerts.
        cid = new_id()
        execute("INSERT INTO users (id,email,password_hash,name,created_at,verified) "
                "VALUES (?,?,?,?,?,1)",
                (cid, f"carer_{cid[:6]}@medeasy.test", "x", "Daughter", now_iso()),
                commit=True)
        execute("INSERT INTO family_members "
                "(id,group_id,user_id,role,alert_missed_doses,share_medicines,"
                " receive_care_alerts,joined_at) VALUES (?,?,?,'admin',0,0,1,?)",
                (new_id(), gid, cid, now_iso()), commit=True)
    return uid


def _overdue_dose():
    return [{"med_id": "m1", "med_name": "Metformin", "time": "09:00", "taken": False}]


def _run_escalation(app, monkeypatch, uid, *, reached):
    """Run _caregiver_alerts once with delivery mocked to reach `reached` people."""
    # Freeze "now" at noon so the 09:00 dose is a deterministic 180 min overdue,
    # regardless of when the test actually runs.
    noon = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(scheduler, "_user_local_now", lambda _uid: noon)
    import db
    monkeypatch.setattr(db, "get_today_doses", _overdue_dose)
    import push, mailer, sms
    monkeypatch.setattr(push, "push_to_user", lambda *a, **k: (1 if reached else 0))
    monkeypatch.setattr(mailer, "send_email", lambda *a, **k: False)
    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    monkeypatch.setattr(sms, "notify_contact", lambda *a, **k: False)
    monkeypatch.setattr(sms, "is_configured", lambda *a, **k: False)
    with app.app_context():
        scheduler._caregiver_alerts()


def _keys(app, uid, prefix):
    with app.app_context():
        rows = execute("SELECT source_id FROM notification_log WHERE user_id=?",
                       (uid,), fetchall=True) or []
    return [r["source_id"] for r in rows if (r["source_id"] or "").startswith(prefix)]


def test_escalation_reaching_nobody_does_not_burn_the_dose(app, monkeypatch):
    uid = _seed_watched_member(app)
    with app.app_context():
        execute("DELETE FROM notification_log WHERE user_id=?", (uid,), commit=True)

    # Delivery fails to reach anyone → the 'caregiver:' key must NOT be written,
    # so the next tick retries. The member is warned once via 'caregiver_fail:'.
    _run_escalation(app, monkeypatch, uid, reached=False)
    assert _keys(app, uid, "caregiver:m1:09:00") == [], \
        "escalation key was burned despite reaching nobody — dose won't retry"
    assert _keys(app, uid, "caregiver_fail:m1:09:00"), \
        "member was not told the family couldn't be reached"

    # A second failed tick must not spam the member again...
    _run_escalation(app, monkeypatch, uid, reached=False)
    assert len(_keys(app, uid, "caregiver_fail:m1:09:00")) == 1

    # ...but once delivery recovers, the escalation fires and is recorded.
    _run_escalation(app, monkeypatch, uid, reached=True)
    assert _keys(app, uid, "caregiver:m1:09:00"), \
        "escalation did not fire after delivery recovered"
