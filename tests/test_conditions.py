"""Condition dashboards — a focused read tying labs + vitals + meds (+ cycle for
PCOS) together for one condition. No new storage; pure aggregation."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.conditions import get_condition_dashboard, list_conditions
from db.labs import log_lab_result

PW = "cond-pw-12345"


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


def _med(uid, name, purpose=""):
    execute("""INSERT INTO medicines (id, name, dosage, active, created_at, purpose, user_id)
               VALUES (?,?,?,1,?,?,?)""",
            (new_id(), name, "1 tab", now_iso(), purpose, uid), commit=True)


def _vital(uid, vtype, v1, v2=None, unit=""):
    execute("""INSERT INTO vitals (id, date_key, type, value1, value2, unit, notes, logged_at, user_id)
               VALUES (?,?,?,?,?,?,'',?,?)""",
            (new_id(), "2026-07-01", vtype, v1, v2, unit, now_iso(), uid), commit=True)


def test_list_conditions():
    keys = {c["key"] for c in list_conditions()}
    assert {"diabetes", "hypertension", "thyroid", "cholesterol", "pcos"} <= keys


def test_unknown_condition_raises(app):
    _, uid = _uid(app, "cond0@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            get_condition_dashboard("gout")


def test_diabetes_ties_labs_vitals_meds(app):
    c, uid = _uid(app, "cond1@medeasy.test")
    with user_context(uid):
        log_lab_result("hba1c", 7.4, "2026-07-01")
        _vital(uid, "blood_sugar", 180, unit="mg/dL")
        _med(uid, "Metformin", "diabetes")
        _med(uid, "Amlodipine", "blood pressure")   # unrelated → excluded
        d = get_condition_dashboard("diabetes")
    hba1c = next(l for l in d["labs"] if l["key"] == "hba1c")
    assert hba1c["value"] == 7.4 and hba1c["status"] == "high" and hba1c["have"]
    bs = next(v for v in d["vitals"] if v["type"] == "blood_sugar")
    assert bs["value1"] == 180 and bs["have"]
    med_names = [m["name"] for m in d["medicines"]]
    assert "Metformin" in med_names and "Amlodipine" not in med_names


def test_missing_labs_flagged_not_errored(app):
    _, uid = _uid(app, "cond2@medeasy.test")
    with user_context(uid):
        d = get_condition_dashboard("thyroid")
    tsh = next(l for l in d["labs"] if l["key"] == "tsh")
    assert tsh["have"] is False and tsh["value"] is None


def test_pcos_includes_cycle(app):
    c, uid = _uid(app, "cond3@medeasy.test")
    with user_context(uid):
        d = get_condition_dashboard("pcos")
    assert "cycle" in d and "regularity" in d["cycle"] and "symptoms" in d["cycle"]


def test_meds_match_by_name_or_purpose(app):
    c, uid = _uid(app, "cond4@medeasy.test")
    with user_context(uid):
        _med(uid, "Thyronorm 50mcg")           # matches by name
        _med(uid, "Some Tablet", "for thyroid")  # matches by purpose
        d = get_condition_dashboard("thyroid")
    assert len(d["medicines"]) == 2


def test_meds_matched_by_whole_word_not_substring(app):
    # Word-boundary matching: unrelated meds must NOT be mislabelled under a
    # condition (Nystatin is an antifungal, not a statin; Sugarfree isn't a
    # diabetes drug; a BPH med isn't a BP med).
    c, uid = _uid(app, "cond6@medeasy.test")
    with user_context(uid):
        _med(uid, "Nystatin")                       # antifungal — NOT cholesterol
        _med(uid, "Sugarfree Gold")                 # sweetener — NOT diabetes
        _med(uid, "Tamsulosin", "for BPH")          # prostate — NOT hypertension
        assert get_condition_dashboard("cholesterol")["medicines"] == []
        assert get_condition_dashboard("diabetes")["medicines"] == []
        assert get_condition_dashboard("hypertension")["medicines"] == []


def test_bp_named_medicine_still_matches(app):
    # The old ' bp' leading-space hack MISSED a med literally named "BP Tablet".
    c, uid = _uid(app, "cond7@medeasy.test")
    with user_context(uid):
        _med(uid, "BP Tablet")
        assert [m["name"] for m in get_condition_dashboard("hypertension")["medicines"]] == ["BP Tablet"]


def test_api_round_trip(app):
    c, uid = _uid(app, "cond5@medeasy.test")
    assert "conditions" in c.get("/api/conditions").get_json()
    r = c.get("/api/conditions/diabetes")
    assert r.status_code == 200 and r.get_json()["name"] == "Diabetes"
    assert c.get("/api/conditions/nope").status_code == 404
