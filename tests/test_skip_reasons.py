"""Missed-dose reasons — optional tag on a skip, summarized into patterns."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.medicines import log_dose, get_skip_reasons, insert_medicine

PW = "skip-pw-12345"


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


def test_reason_stored_only_on_skip(app):
    _, uid = _uid(app, "skip1@medeasy.test")
    today = dt.date.today().isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        # skip with a reason
        log_dose(mid, today, "09:00", taken=False, reason="forgot")
        row = execute("SELECT taken, skip_reason FROM dose_logs WHERE medicine_id=? AND date_key=?",
                      (mid, today), fetchone=True)
        assert row["taken"] == 0 and row["skip_reason"] == "forgot"
        # taking it clears the reason
        log_dose(mid, today, "09:00", taken=True, reason="forgot")
        row = execute("SELECT taken, skip_reason FROM dose_logs WHERE medicine_id=? AND date_key=?",
                      (mid, today), fetchone=True)
        assert row["taken"] == 1 and row["skip_reason"] is None


def test_unknown_reason_dropped(app):
    _, uid = _uid(app, "skip2@medeasy.test")
    today = dt.date.today().isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        log_dose(mid, today, "09:00", taken=False, reason="banana")
        row = execute("SELECT skip_reason FROM dose_logs WHERE medicine_id=? AND date_key=?",
                      (mid, today), fetchone=True)
        assert row["skip_reason"] is None      # not in the closed set → dropped


def test_summary_counts_and_top(app):
    _, uid = _uid(app, "skip3@medeasy.test")
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        for i in range(1, 4):
            d = (dt.date.today() - dt.timedelta(days=i)).isoformat()
            log_dose(mid, d, "09:00", taken=False, reason="away")
        log_dose(mid, (dt.date.today() - dt.timedelta(days=4)).isoformat(), "09:00", taken=False, reason="forgot")
        s = get_skip_reasons(30)
        by = {r["reason"]: r["count"] for r in s["reasons"]}
        assert by["away"] == 3 and by["forgot"] == 1
        assert s["total"] == 4 and s["top"] == "away"
        assert s["reasons"][0]["reason"] == "away"    # sorted by count desc


def test_untagged_skips_not_counted(app):
    _, uid = _uid(app, "skip4@medeasy.test")
    today = dt.date.today().isoformat()
    with user_context(uid):
        mid = insert_medicine({"name": "Med", "frequency": "once_daily", "times": ["09:00"]})["id"]
        log_dose(mid, today, "09:00", taken=False)   # skipped, no reason
        s = get_skip_reasons()
        assert s["has_data"] is False and s["total"] == 0


def test_api_round_trip(app):
    c, uid = _uid(app, "skip5@medeasy.test")
    mid = c.post("/api/medicines", json={"name": "Med", "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]["id"]
    today = dt.date.today().isoformat()
    assert c.post(f"/api/medicines/{mid}/log", json={"date": today, "time": "09:00", "taken": False, "reason": "ran_out"}).status_code == 200
    s = c.get("/api/medicines/skip-reasons").get_json()
    assert s["top"] == "ran_out" and s["total"] == 1
