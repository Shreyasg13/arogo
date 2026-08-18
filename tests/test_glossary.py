"""Plain-language glossary — 'what this measures', never a verdict.

Guards: every catalog lab has a definition, definitions carry no interpretation
words, the payload leads with the user's own terms, and medicine notes come only
from the curated formulary (never invented).
"""
import re
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.glossary import get_glossary, LAB_GLOSSARY, VITAL_GLOSSARY

PW = "gloss-pw-12345"


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


# ── coverage ────────────────────────────────────────────────────────────────

def test_every_catalog_lab_has_a_definition():
    from lab_catalog import CATALOG
    missing = [t["key"] for t in CATALOG if not LAB_GLOSSARY.get(t["key"])]
    assert not missing, f"labs without a plain-language definition: {missing}"


def test_definitions_carry_no_verdict_language():
    """The honesty contract: definitional only — no interpretation of a value."""
    banned = re.compile(
        r"\b(normal|abnormal|healthy|unhealthy|too high|too low|dangerous|"
        r"you should|you must|diagnos|treat|cure|risk of|good news|bad news)\b", re.I)
    for text in list(LAB_GLOSSARY.values()) + list(VITAL_GLOSSARY.values()):
        assert not banned.search(text), f"verdict/advice language in glossary: {text!r}"


# ── personalisation ─────────────────────────────────────────────────────────

def test_leads_with_your_own_terms(app):
    _, uid = _uid(app, "gloss1@medeasy.test")
    with user_context(uid):
        # log an HbA1c and a blood-pressure vital
        execute("INSERT INTO lab_results (id,lab_key,name,value,unit,date_key,created_at,user_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), "hba1c", "HbA1c", 5.4, "%", "2026-08-01", now_iso(), uid), commit=True)
        execute("INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), "2026-08-01", "blood_pressure", 120, 80, "mmHg", now_iso(), uid), commit=True)
        g = get_glossary()
    lab_keys = {x["key"] for x in g["yours"]["labs"]}
    vital_keys = {x["key"] for x in g["yours"]["vitals"]}
    assert "hba1c" in lab_keys
    assert "blood_pressure" in vital_keys
    # 'all' is always the full reference set regardless of what you've logged
    assert len(g["all"]["labs"]) >= 20 and len(g["all"]["vitals"]) >= 5


def test_empty_user_still_gets_reference(app):
    _, uid = _uid(app, "gloss2@medeasy.test")
    with user_context(uid):
        g = get_glossary()
    assert g["yours"]["labs"] == [] and g["yours"]["vitals"] == []
    assert g["all"]["labs"], "reference labs must be present even with no data"
    # every 'all' entry has a definition
    assert all(x["plain"] for x in g["all"]["labs"])


# ── medicine notes only from the curated formulary ──────────────────────────

def test_medicine_note_only_from_formulary(app):
    _, uid = _uid(app, "gloss3@medeasy.test")
    with user_context(uid):
        # a made-up drug name must NOT get an invented description
        execute("INSERT INTO medicines (id,name,dosage,user_id,created_at) VALUES (?,?,?,?,?)",
                (new_id(), "Zzxq Madeup 500", "1", uid, now_iso()), commit=True)
        g = get_glossary()
    med = next((m for m in g["yours"]["medicines"] if m["term"] == "Zzxq Madeup 500"), None)
    assert med is not None
    assert med["plain"] is None, "unknown drug must not be given a fabricated note"


# ── route ───────────────────────────────────────────────────────────────────

def test_route_requires_auth(app):
    c = app.test_client()
    assert c.get("/api/glossary").status_code in (401, 403)


def test_route_shape(app):
    c, _ = _uid(app, "gloss4@medeasy.test")
    body = c.get("/api/glossary").get_json()
    assert "yours" in body and "all" in body
    assert "labs" in body["all"] and "vitals" in body["all"]
