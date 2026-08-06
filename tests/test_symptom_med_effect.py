"""Symptom before/after a medicine change — an observation, not a proven cause."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.symptom_insights import get_symptom_med_effectiveness

PW = "sme-pw-12345"


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


def _ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def _symptom(uid, name, days_ago, severity=5):
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), name, severity, _ago(days_ago), 'evening', '', now_iso(), uid), commit=True)


def _event(uid, med_name, kind, days_ago):
    execute("""INSERT INTO medicine_events (id,medicine_id,med_name,kind,detail,at,user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id(), new_id(), med_name, kind, '', _ago(days_ago) + 'T09:00:00', uid), commit=True)


def test_improvement_detected(app):
    _, uid = _uid(app, "sme1@medeasy.test")
    # Med started 30 days ago. Before (days 31–58): 5 headaches. After (days 2–29): 1.
    _event(uid, "Propranolol", "started", 30)
    for d in (58, 52, 45, 40, 33):
        _symptom(uid, "Headache", d, severity=7)
    _symptom(uid, "Headache", 10, severity=4)
    with user_context(uid):
        d = get_symptom_med_effectiveness()
    f = next((x for x in d["findings"] if x["symptom"] == "Headache"), None)
    assert f is not None
    assert f["medicine"] == "Propranolol" and f["event"] == "started"
    assert f["before_count"] == 5 and f["after_count"] == 1
    assert f["direction"] == "improved"
    assert f["before_severity"] == 7.0 and f["after_severity"] == 4.0


def test_needs_baseline(app):
    _, uid = _uid(app, "sme2@medeasy.test")
    _event(uid, "Med", "started", 30)
    _symptom(uid, "Nausea", 33)                     # only 1 before → no baseline
    _symptom(uid, "Nausea", 10)
    with user_context(uid):
        d = get_symptom_med_effectiveness()
    assert not any(x["symptom"] == "Nausea" for x in d["findings"])


def test_incomplete_after_window_skipped(app):
    _, uid = _uid(app, "sme3@medeasy.test")
    _event(uid, "Med", "started", 10)               # after window (28d) not elapsed
    for d in (12, 14, 16):
        _symptom(uid, "Dizziness", d)
    with user_context(uid):
        d = get_symptom_med_effectiveness()
    assert not any(x["symptom"] == "Dizziness" for x in d["findings"])


def test_api(app):
    c, uid = _uid(app, "sme4@medeasy.test")
    body = c.get("/api/symptoms/med-effect").get_json()
    assert "findings" in body and "note" in body and "cause" in body["note"].lower()
