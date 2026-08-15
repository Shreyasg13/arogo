"""N2 always-current health binder — one printable summary composed from the
user's own records (identity, blood type, advance-care wishes, live meds,
allergies, conditions, recent labs, vaccines, dental/vision). Read-only, honest,
empty sections stay empty, and strictly user-scoped."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.health import save_emergency_info
from db.health_binder import get_health_binder

PW = "binder-pw-12345"


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


def _med(uid, name, active=1):
    execute("""INSERT INTO medicines (id,name,dosage,unit,frequency,active,created_at,user_id)
               VALUES (?,?,?,?,'once_daily',?,?,?)""",
            (new_id(), name, "10", "mg", active, now_iso(), uid), commit=True)


def test_binder_composes_all_sections(app):
    c, uid = _uid(app, "binder1@medeasy.test")
    with user_context(uid):
        save_emergency_info({"blood_type": "B+", "conditions": "Type 2 Diabetes",
                             "organ_donor": "Registered donor",
                             "directive_wishes": "Comfort care.",
                             "contact1_name": "Meera", "contact1_phone": "+91 90000 22222"})
        _med(uid, "Metformin", active=1)
        _med(uid, "OldDrug", active=0)
        execute("""INSERT INTO lab_results (id,lab_key,name,value,unit,date_key,created_at,user_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (new_id(), "hba1c", "HbA1c", 7.2, "%", "2026-08-01", now_iso(), uid), commit=True)
        execute("""INSERT INTO immunizations (id,vaccine_key,name,date_given,created_at,user_id)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), "tetanus", "Tetanus (Td)", "2025-06-01", now_iso(), uid), commit=True)
        b = get_health_binder()
    assert b["blood_type"] == "B+"
    assert b["conditions"] == "Type 2 Diabetes"
    assert b["advance_care"]["organ_donor"] == "Registered donor"
    assert [m["name"] for m in b["active_medicines"]] == ["Metformin"]     # live, active-only
    assert any(l["name"] == "HbA1c" and l["value"] == 7.2 for l in b["labs"])
    assert any(v["name"].startswith("Tetanus") for v in b["vaccines"])
    assert b["contacts"] == [{"name": "Meera", "phone": "+91 90000 22222"}]
    assert b["generated"][:4].isdigit()


def test_empty_binder_has_empty_sections_not_phantoms(app):
    _, uid = _uid(app, "binder2@medeasy.test")
    with user_context(uid):
        b = get_health_binder()
    assert b["labs"] == [] and b["vaccines"] == [] and b["active_medicines"] == []
    assert b["blood_type"] == "" and b["contacts"] == []
    assert b["dental_vision"]["rx"] is None and b["dental_vision"]["due"] == []


def test_binder_is_user_scoped(app):
    ca, uid_a = _uid(app, "binder3@medeasy.test")
    _, uid_b = _uid(app, "binder4@medeasy.test")
    with user_context(uid_a):
        _med(uid_a, "SecretDrugA")
    with user_context(uid_b):
        b = get_health_binder()
    assert all(m["name"] != "SecretDrugA" for m in b["active_medicines"])


def test_api_endpoint(app):
    c, uid = _uid(app, "binder5@medeasy.test")
    with user_context(uid):
        save_emergency_info({"blood_type": "O-"})
    r = c.get("/api/health-binder")
    assert r.status_code == 200 and r.get_json()["blood_type"] == "O-"


def test_api_requires_auth(app):
    assert app.test_client().get("/api/health-binder").status_code in (401, 403)
