"""Emergency QR for the health-ID card — real QR via segno, graceful without it."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import build_emergency_qr, _emergency_qr_text, save_emergency_info

PW = "eqr-pw-12345"


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


def test_no_info_no_qr(app):
    _, uid = _uid(app, "eqr1@medeasy.test")
    with user_context(uid):
        d = build_emergency_qr()
    assert d["available"] is False and d["reason"] == "no_emergency_info"


def test_text_summary_built(app):
    _, uid = _uid(app, "eqr2@medeasy.test")
    with user_context(uid):
        save_emergency_info({"blood_type": "O+", "allergies": "Penicillin",
                             "conditions": "Diabetes", "contact1_name": "Sita",
                             "contact1_phone": "9876500000"})
        txt = _emergency_qr_text()
    assert txt.startswith("EMERGENCY")
    assert "Blood: O+" in txt and "Penicillin" in txt and "ICE: Sita 9876500000" in txt


def test_qr_or_graceful(app):
    """With info present: a real SVG if segno is installed, else a clean
    'library missing' signal — never a broken QR."""
    _, uid = _uid(app, "eqr3@medeasy.test")
    with user_context(uid):
        save_emergency_info({"blood_type": "B+", "contact1_name": "Ravi", "contact1_phone": "900000"})
        d = build_emergency_qr()
    if d["available"]:
        assert d["svg"] and "<svg" in d["svg"]
    else:
        assert d["reason"] == "qr_lib_missing" and d["svg"] is None


def test_qr_positive_when_segno_present(app):
    pytest.importorskip("segno")
    _, uid = _uid(app, "eqr4@medeasy.test")
    with user_context(uid):
        save_emergency_info({"blood_type": "A+", "conditions": "Asthma"})
        d = build_emergency_qr()
    assert d["available"] is True and d["svg"].strip().startswith("<")


def test_api(app):
    c, uid = _uid(app, "eqr5@medeasy.test")
    with user_context(uid):
        save_emergency_info({"blood_type": "AB+"})
    body = c.get("/api/health-id/qr").get_json()
    assert "available" in body
