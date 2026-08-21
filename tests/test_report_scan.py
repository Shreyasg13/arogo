"""Document scan → confirm-before-save readings from an uploaded report."""
import os
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute, new_id, now_iso

PW = "scan-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _client_uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]
    return c, uid


def _report(app, uid, ext, text):
    """Write a real file into UPLOAD_FOLDER and insert an owned reports row."""
    folder = app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    fn = new_id() + "." + ext
    with open(os.path.join(folder, fn), "w", encoding="utf-8") as f:
        f.write(text)
    rid = new_id()
    execute("""INSERT INTO reports (id,filename,original_name,report_type,report_date,upload_date,file_ext,user_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, fn, "report." + ext, "lab", "2026-08-01", now_iso(), ext, uid), commit=True)
    return rid, os.path.join(folder, fn)


def test_proposes_readings_from_text_report(app):
    c, uid = _client_uid(app, "scan1@medeasy.test")
    rid, path = _report(app, uid, "txt",
                        "Blood Pressure: 120/80 mmHg\nBlood Sugar: 110 mg/dL\nHeart Rate: 72 bpm\n")
    try:
        d = c.get(f"/api/reports/{rid}/readings").get_json()
    finally:
        os.remove(path)
    types = {r["type"] for r in d["readings"]}
    assert "blood_pressure" in types
    assert d["date_key"] == "2026-08-01"          # dated to the test, not the upload
    assert "ocr_available" in d and d["is_image"] is False


def test_image_without_ocr_degrades_honestly(app):
    c, uid = _client_uid(app, "scan2@medeasy.test")
    # a fake png (content irrelevant — we only exercise the no-OCR branch)
    rid, path = _report(app, uid, "png", "not really an image")
    try:
        import rx_parse
        d = c.get(f"/api/reports/{rid}/readings").get_json()
    finally:
        os.remove(path)
    assert d["is_image"] is True
    assert d["readings"] == []
    if not rx_parse.ocr_available():
        assert "OCR" in d["reason"] or "tesseract" in d["reason"].lower()  # honest, not a crash


def test_confirmed_readings_save_and_validate(app):
    c, uid = _client_uid(app, "scan3@medeasy.test")
    rid, path = _report(app, uid, "txt", "x")
    try:
        # user confirms one good BP reading and one impossible one
        body = {"date_key": "2026-08-01", "readings": [
            {"type": "blood_pressure", "value1": 120, "value2": 80, "unit": "mmHg"},
            {"type": "blood_pressure", "value1": 900, "value2": 800, "unit": "mmHg"},  # implausible
        ]}
        r = c.post(f"/api/reports/{rid}/readings/save", json=body).get_json()
    finally:
        os.remove(path)
    assert r["success"] and r["saved"] == 1 and r["failed"] == 1   # bad OCR value rejected
    # the good one landed in vitals
    n = dict(execute("SELECT COUNT(*) c FROM vitals WHERE user_id=? AND type='blood_pressure'",
                     (uid,), fetchone=True))["c"]
    assert n == 1


def test_readings_require_auth_and_ownership(app):
    c, _ = _client_uid(app, "scan4@medeasy.test")
    assert c.get("/api/reports/nope/readings").status_code == 404          # not your report
    assert app.test_client().get("/api/reports/x/readings").status_code in (401, 403)
