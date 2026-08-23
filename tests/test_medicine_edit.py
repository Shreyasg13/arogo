"""Editing a medicine in place — especially re-timing, without losing history.

Before this, changing a dose time meant delete + re-add, which destroyed the
medicine's entire dose history. These tests pin the semantics: the schedule
changes going forward, and what actually happened in the past stays true.
"""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, user_today
from db.medicines import (insert_medicine, update_medicine, get_medicine,
                          log_dose, get_today_doses)

PW = "medit-pw-12345"


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


def _med(**kw):
    base = {"name": "Metformin", "dosage": "500", "unit": "mg",
            "frequency": "twice_daily", "times": ["08:00", "20:00"]}
    base.update(kw)
    return insert_medicine(base)


def test_missing_medicine_is_rejected(app):
    _, uid = _uid(app, "medit1@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            update_medicine("nope", {"name": "x"})


def test_retime_changes_schedule(app):
    _, uid = _uid(app, "medit2@medeasy.test")
    with user_context(uid):
        m = _med()
        out = update_medicine(m["id"], {"times": ["09:00", "21:00"]})
        doses = {d["time"] for d in get_today_doses()}
    assert out["times"] == ["09:00", "21:00"]
    assert doses == {"09:00", "21:00"}          # today's plan follows the new times


def test_retime_moves_todays_untaken_dose_but_not_taken_history(app):
    _, uid = _uid(app, "medit3@medeasy.test")
    today = user_today()
    with user_context(uid):
        m = _med(times=["08:00", "20:00"])
        log_dose(m["id"], today, "08:00", True)      # morning already taken
        update_medicine(m["id"], {"times": ["09:00", "21:00"]})
        rows = execute("""SELECT time_key, taken FROM dose_logs
                          WHERE medicine_id=? AND date_key=? ORDER BY time_key""",
                       (m["id"], today), fetchall=True)
    keys = {(r["time_key"], r["taken"]) for r in rows}
    # The taken 08:00 dose stays where it happened — history is not rewritten.
    assert ("08:00", 1) in keys
    assert ("09:00", 1) not in keys


def test_past_logs_are_never_rewritten(app):
    _, uid = _uid(app, "medit4@medeasy.test")
    with user_context(uid):
        m = _med(times=["08:00"])
        log_dose(m["id"], "2026-01-05", "08:00", True)   # historical record
        update_medicine(m["id"], {"times": ["11:00"]})
        row = execute("""SELECT time_key FROM dose_logs
                         WHERE medicine_id=? AND date_key='2026-01-05'""",
                      (m["id"],), fetchone=True)
    assert row["time_key"] == "08:00"            # what happened, stays


def test_validation_matches_create(app):
    _, uid = _uid(app, "medit5@medeasy.test")
    with user_context(uid):
        m = _med()
        # garbage times fall back to the validated default, never stored raw
        out = update_medicine(m["id"], {"times": ["99:99", "bogus"]})
        assert out["times"] == ["08:00"]
        # an icon containing markup is rejected at source
        out = update_medicine(m["id"], {"icon": "<img src=x>"})
        assert "<" not in out["icon"]
        # blank name keeps the existing one rather than wiping it
        out = update_medicine(m["id"], {"name": "   "})
        assert out["name"] == "Metformin"


def test_as_needed_clears_times_and_schedule(app):
    _, uid = _uid(app, "medit6@medeasy.test")
    with user_context(uid):
        m = _med(times=["08:00"], schedule_days=[0, 2, 4])
        out = update_medicine(m["id"], {"frequency": "as_needed"})
    assert out["times"] == [] and out["schedule_days"] is None


def test_partial_edit_leaves_other_fields_alone(app):
    _, uid = _uid(app, "medit7@medeasy.test")
    with user_context(uid):
        m = _med(notes="take with water", purpose="diabetes", cost=250)
        out = update_medicine(m["id"], {"times": ["10:00"]})
    assert out["notes"] == "take with water"
    assert out["purpose"] == "diabetes"
    assert out["cost"] == 250
    assert out["dosage"] == "500"


def test_edit_is_recorded_in_history(app):
    from db.medicines import get_medicine_events
    _, uid = _uid(app, "medit8@medeasy.test")
    with user_context(uid):
        m = _med(times=["08:00"])
        update_medicine(m["id"], {"times": ["09:00"]})
        kinds = [(e["kind"], e["detail"]) for e in get_medicine_events(days=1)]
    assert any(k == "edited" and "08:00" in d and "09:00" in d for k, d in kinds)


def test_isolation(app):
    _, a = _uid(app, "medit9a@medeasy.test")
    _, b = _uid(app, "medit9b@medeasy.test")
    with user_context(a):
        m = _med()
    with user_context(b):
        with pytest.raises(ValueError):
            update_medicine(m["id"], {"name": "hacked"})
    with user_context(a):
        assert get_medicine(m["id"])["name"] == "Metformin"


def test_route(app):
    c, uid = _uid(app, "medit10@medeasy.test")
    with user_context(uid):
        m = _med()
    r = c.patch(f"/api/medicines/{m['id']}", json={"times": ["07:30"]}).get_json()
    assert r["success"] and r["medicine"]["times"] == ["07:30"]
    assert c.patch("/api/medicines/missing", json={"times": ["07:30"]}).status_code == 404


def test_route_requires_auth(app):
    assert app.test_client().patch("/api/medicines/x", json={}).status_code in (401, 403)
