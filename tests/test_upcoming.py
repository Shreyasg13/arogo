"""Forward-looking upcoming aggregator — merges appointments, lab rechecks,
prescription renewals, vaccines and dependent events; excludes the past."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.health import create_appointment
from db.labs import log_lab_result, set_lab_recheck
from db.prescriptions import create_prescription
from db.dependents import create_dependent
from db.upcoming import get_upcoming

PW = "upc-pw-123456"


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


def _ahead(n):
    return (_dt.date.today() + _dt.timedelta(days=n)).isoformat()


def _ago(n):
    return (_dt.date.today() - _dt.timedelta(days=n)).isoformat()


def _types(res):
    return {e["type"] for e in res["events"]}


def test_appointment_shows_and_past_excluded(app):
    _, uid = _uid(app, "upc1@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "Cardiology", "date": _ahead(3)})
        create_appointment({"title": "Old visit", "date": _ago(3)})
        res = get_upcoming(60)
    titles = [e["name"] for e in res["events"] if e["type"] == "appointment"]
    assert "Cardiology" in titles and "Old visit" not in titles


def test_lab_recheck_due_shows(app):
    _, uid = _uid(app, "upc2@medeasy.test")
    with user_context(uid):
        log_lab_result("hba1c", 6.5, _ago(100))
        set_lab_recheck("hba1c", 90)               # overdue by ~10 days
        res = get_upcoming(60)
    lab = next((e for e in res["events"] if e["type"] == "lab_recheck"), None)
    assert lab is not None and lab["name"] == "HbA1c" and lab["days_until"] < 0
    assert res["overdue_count"] >= 1


def test_prescription_renewal_shows(app):
    _, uid = _uid(app, "upc3@medeasy.test")
    with user_context(uid):
        create_prescription({"prescriber": "Dr Nair", "valid_until": _ahead(5)})
        res = get_upcoming(60)
    assert any(e["type"] == "rx_renewal" and e["name"] == "Dr Nair" for e in res["events"])


def test_dependent_future_record_shows(app):
    _, uid = _uid(app, "upc4@medeasy.test")
    with user_context(uid):
        dep = create_dependent("Aarav", "child")
        execute("""INSERT INTO dependent_records (id,dependent_id,kind,label,detail,date_key,created_at,user_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), dep["id"], "vaccine", "MMR dose", "", _ahead(4), now_iso(), uid), commit=True)
        res = get_upcoming(60)
    dep_ev = next((e for e in res["events"] if e["type"] == "dependent"), None)
    assert dep_ev is not None and dep_ev["who"] == "Aarav" and dep_ev["name"] == "MMR dose"


def test_window_filters_beyond_days(app):
    _, uid = _uid(app, "upc5@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "Near", "date": _ahead(5)})
        create_appointment({"title": "Far", "date": _ahead(90)})
        res = get_upcoming(30)                      # 90 days out is beyond the window
    names = [e["name"] for e in res["events"]]
    assert "Near" in names and "Far" not in names


def test_sorted_by_date(app):
    _, uid = _uid(app, "upc6@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "Later", "date": _ahead(10)})
        create_appointment({"title": "Sooner", "date": _ahead(2)})
        res = get_upcoming(60)
    dates = [e["date"] for e in res["events"]]
    assert dates == sorted(dates)


def test_this_week_count(app):
    _, uid = _uid(app, "upc7@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "A", "date": _ahead(2)})
        create_appointment({"title": "B", "date": _ahead(20)})
        res = get_upcoming(60)
    assert res["this_week"] == 1


def test_api_endpoint(app):
    c, uid = _uid(app, "upc8@medeasy.test")
    with user_context(uid):
        create_appointment({"title": "Lab", "date": _ahead(3)})
    r = c.get("/api/upcoming?days=60")
    assert r.status_code == 200 and any(e["name"] == "Lab" for e in r.get_json()["events"])
