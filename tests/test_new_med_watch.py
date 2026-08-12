"""I5 — new-medication side-effect watch. For meds started recently, list the
symptoms logged since that start date. TIMING only, never a causal claim; every
symptom is one the user logged. Meds with no symptoms since start don't appear."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id
from db.medicines import insert_medicine, get_new_med_watch

PW = "nmw-pw-123456"


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


def _symptom(uid, name, day, severity=3):
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,logged_at,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (new_id(), name, severity, day, "morning", "", f"{day}T09:00:00", uid), commit=True)


def test_empty_without_recent_meds(app):
    _, uid = _uid(app, "nmw1@medeasy.test")
    with user_context(uid):
        d = get_new_med_watch()
    assert d["has_data"] is False and d["meds"] == []


def test_symptoms_since_start_are_grouped(app):
    _, uid = _uid(app, "nmw2@medeasy.test")
    today = dt.date.today()
    start = (today - dt.timedelta(days=10)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "Metformin", "frequency": "once_daily",
                         "times": ["09:00"], "start_date": start})
        # Two headaches + one nausea AFTER the start date.
        _symptom(uid, "Headache", (today - dt.timedelta(days=8)).isoformat(), 4)
        _symptom(uid, "Headache", (today - dt.timedelta(days=3)).isoformat(), 5)
        _symptom(uid, "Nausea",   (today - dt.timedelta(days=2)).isoformat(), 2)
        d = get_new_med_watch()
    assert d["has_data"] is True
    med = d["meds"][0]
    assert med["name"] == "Metformin" and med["days_since"] == 10
    names = {s["name"]: s for s in med["symptoms"]}
    assert names["Headache"]["count"] == 2 and names["Headache"]["worst"] == 5
    assert names["Nausea"]["count"] == 1
    assert med["symptom_count"] == 3


def test_symptoms_before_start_are_excluded(app):
    _, uid = _uid(app, "nmw3@medeasy.test")
    today = dt.date.today()
    start = (today - dt.timedelta(days=5)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "Statin", "frequency": "once_daily",
                         "times": ["21:00"], "start_date": start})
        # Symptom a week before the med started — must NOT be attributed.
        _symptom(uid, "Cough", (today - dt.timedelta(days=12)).isoformat())
        d = get_new_med_watch()
    assert d["has_data"] is False   # nothing logged since start → med omitted


def test_old_med_is_not_watched(app):
    _, uid = _uid(app, "nmw4@medeasy.test")
    today = dt.date.today()
    old_start = (today - dt.timedelta(days=200)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "OldMed", "frequency": "once_daily",
                         "times": ["09:00"], "start_date": old_start})
        _symptom(uid, "Fatigue", (today - dt.timedelta(days=2)).isoformat())
        d = get_new_med_watch(recent_days=45)
    assert d["has_data"] is False   # started 200 days ago → outside the watch window


def test_api(app):
    c, uid = _uid(app, "nmw5@medeasy.test")
    today = dt.date.today()
    start = (today - dt.timedelta(days=3)).isoformat()
    with user_context(uid):
        insert_medicine({"name": "New", "frequency": "once_daily", "times": ["08:00"], "start_date": start})
        _symptom(uid, "Dizziness", (today - dt.timedelta(days=1)).isoformat())
    body = c.get("/api/medicines/new-med-watch?days=45").get_json()
    assert body["has_data"] is True and body["meds"][0]["symptoms"][0]["name"] == "Dizziness"
