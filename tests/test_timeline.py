"""Health timeline — merges dated events from meds/symptoms/vitals/labs/
appointments/vaccines into one newest-first story, and EXCLUDES private diary
categories (journal/mood/cycle)."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.timeline import get_timeline
from db.labs import log_lab_result
from db.immunizations import log_dose

PW = "tl-pw-12345"


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


def _seed(uid, c):
    execute("""INSERT INTO medicines (id,name,dosage,active,created_at,purpose,user_id)
               VALUES (?,?,?,1,?,?,?)""",
            (new_id(), "Metformin", "500mg", "2026-05-01T09:00:00", "diabetes", uid), commit=True)
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,logged_at,user_id)
               VALUES (?,?,?,?,?,'',?,?)""",
            (new_id(), "Headache", 6, "2026-07-10", "evening", now_iso(), uid), commit=True)
    execute("""INSERT INTO vitals (id,date_key,type,value1,value2,unit,notes,logged_at,user_id)
               VALUES (?,?,?,?,?,?,'',?,?)""",
            (new_id(), "2026-07-15", "blood_pressure", 130, 85, "mmHg", now_iso(), uid), commit=True)
    with user_context(uid):
        log_lab_result("hba1c", 7.2, "2026-07-20")
        log_dose("td", "2026-06-01", "Booster")
    c.post("/api/appointments", json={"title": "Dr. Rao", "kind": "doctor", "date": "2026-08-30"})


def test_merges_all_sources_newest_first(app):
    c, uid = _uid(app, "tl1@medeasy.test")
    _seed(uid, c)
    with user_context(uid):
        tl = get_timeline()
    kinds = {e["type"] for e in tl["events"]}
    assert {"medicine", "symptom", "vital", "lab", "vaccine", "appointment"} <= kinds
    # Newest first: the Aug appointment precedes the May medicine.
    dates = [e["date"] for e in tl["events"]]
    assert dates == sorted(dates, reverse=True)
    # A lab shows its value + range flag in the detail.
    lab = next(e for e in tl["events"] if e["type"] == "lab")
    assert "7.2" in lab["detail"] and "↑" in lab["detail"]      # 7.2 above the HbA1c range


def test_type_filter(app):
    c, uid = _uid(app, "tl2@medeasy.test")
    _seed(uid, c)
    with user_context(uid):
        only_labs = get_timeline(types=["lab"])
    assert only_labs["events"] and all(e["type"] == "lab" for e in only_labs["events"])


def test_excludes_private_categories(app):
    # Journal/mood/cycle must never appear in the timeline.
    c, uid = _uid(app, "tl3@medeasy.test")
    c.post("/api/thoughts", json={"content": "SECRET diary", "mood": "sad", "date_key": "2026-07-01"})
    c.post("/api/cycle/start", json={"start_date": "2026-07-01"})
    with user_context(uid):
        tl = get_timeline()
    blob = str(tl).lower()
    assert "secret" not in blob and "diary" not in blob
    assert all(e["type"] in {"medicine", "symptom", "vital", "lab", "appointment", "vaccine"}
               for e in tl["events"])


def test_empty_is_clean(app):
    _, uid = _uid(app, "tl4@medeasy.test")
    with user_context(uid):
        tl = get_timeline()
    assert tl["events"] == [] and tl["total"] == 0 and tl["types"]


def test_api_round_trip(app):
    c, uid = _uid(app, "tl5@medeasy.test")
    _seed(uid, c)
    r = c.get("/api/timeline").get_json()
    assert r["total"] >= 6
    r2 = c.get("/api/timeline?types=lab,vaccine").get_json()
    assert all(e["type"] in {"lab", "vaccine"} for e in r2["events"])
