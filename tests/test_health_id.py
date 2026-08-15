"""Printable health ID card — composes profile + emergency info + LIVE active
medicines, read-only and honest (empty fields simply don't appear)."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.health import save_emergency_info
from db.health_id import get_health_id

PW = "hid-pw-12345"


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


def _profile(uid, name, age, gender):
    # Registration may auto-create an empty profile row; replace it so the
    # composer's LIMIT-1 read sees our values.
    execute("DELETE FROM user_profile WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO user_profile (id,name,age,gender,updated_at,user_id) VALUES (?,?,?,?,?,?)",
            (new_id(), name, age, gender, now_iso(), uid), commit=True)


def _med(uid, name, dosage, unit, active=1):
    execute("""INSERT INTO medicines (id,name,dosage,unit,frequency,active,created_at,user_id)
               VALUES (?,?,?,?,'once_daily',?,?,?)""",
            (new_id(), name, dosage, unit, active, now_iso(), uid), commit=True)


def test_composes_identity_and_emergency(app):
    _, uid = _uid(app, "hid1@medeasy.test")
    with user_context(uid):
        _profile(uid, "Asha", 34, "female")
        save_emergency_info({"blood_type": "O+", "allergies": "Penicillin",
                             "contact1_name": "Ravi", "contact1_phone": "+91 90000 11111"})
        card = get_health_id()
    assert card["identity"]["name"] == "Asha" and card["identity"]["age"] == 34
    assert card["blood_type"] == "O+" and card["allergies"] == "Penicillin"
    assert card["contacts"] == [{"name": "Ravi", "phone": "+91 90000 11111"}]


def test_active_medicines_are_live(app):
    # The card pulls REAL active meds from the tracker, not the free-text box.
    _, uid = _uid(app, "hid2@medeasy.test")
    with user_context(uid):
        _med(uid, "Metformin", "500", "mg", active=1)
        _med(uid, "Old Drug", "10", "mg", active=0)      # inactive → excluded
        card = get_health_id()
    names = [m["name"] for m in card["active_medicines"]]
    assert names == ["Metformin"]
    assert card["active_medicines"][0]["dose"] == "500 mg"


def test_empty_card_has_no_phantom_fields(app):
    _, uid = _uid(app, "hid3@medeasy.test")
    with user_context(uid):
        card = get_health_id()
    assert card["identity"]["name"] == "" and card["identity"]["age"] is None
    assert card["blood_type"] == "" and card["active_medicines"] == [] and card["contacts"] == []


def test_isolation_between_users(app):
    _, uid_a = _uid(app, "hid4@medeasy.test")
    _, uid_b = _uid(app, "hid5@medeasy.test")
    with user_context(uid_a):
        _med(uid_a, "SecretDrugA", "1", "mg")
    with user_context(uid_b):
        card_b = get_health_id()
    assert all(m["name"] != "SecretDrugA" for m in card_b["active_medicines"])


def test_advance_care_wishes_persist_and_surface(app):
    # M1 — the user's own advance-care wishes save on the emergency card and
    # appear verbatim on the health-ID card. Never interpreted, only stored.
    c, uid = _uid(app, "hid7@medeasy.test")
    with user_context(uid):
        save_emergency_info({"organ_donor": "Registered donor",
                             "directive_wishes": "No heroic measures; comfort care only.",
                             "directive_location": "Home safe, top drawer"})
        card = get_health_id()
    ac = card["advance_care"]
    assert ac["organ_donor"] == "Registered donor"
    assert ac["directive_wishes"] == "No heroic measures; comfort care only."
    assert ac["directive_location"] == "Home safe, top drawer"
    # And through the HTTP round-trip.
    body = c.get("/api/health-id").get_json()
    assert body["advance_care"]["organ_donor"] == "Registered donor"


def test_advance_care_empty_by_default(app):
    _, uid = _uid(app, "hid8@medeasy.test")
    with user_context(uid):
        card = get_health_id()
    assert card["advance_care"] == {"organ_donor": "", "directive_wishes": "", "directive_location": ""}


def test_api_endpoint(app):
    c, uid = _uid(app, "hid6@medeasy.test")
    with user_context(uid):
        _profile(uid, "Dev", 40, "male")
        _med(uid, "Aspirin", "75", "mg")
    r = c.get("/api/health-id")
    assert r.status_code == 200
    body = r.get_json()
    assert body["identity"]["name"] == "Dev"
    assert body["active_medicines"][0]["name"] == "Aspirin"
