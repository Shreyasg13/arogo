"""Records vault: free-text report types get bucketed into filterable groups,
and the /api/reports?type= filter narrows the list to a bucket."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.reports import _doc_bucket, list_reports

PW = "vault-pw-12345"


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


def _report(uid, report_type):
    execute("""INSERT INTO reports (id, filename, original_name, patient_name, report_type,
               report_date, upload_date, tags, analysis_notes, severity, doctor, file_ext, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (new_id(), 'f.pdf', report_type + '.pdf', 'Me', report_type,
             '2026-07-01', now_iso(), '[]', '', 'normal', '', 'pdf', uid), commit=True)


def test_bucketing_keywords():
    assert _doc_bucket("Complete Blood Count") == "lab"
    assert _doc_bucket("Lipid Profile") == "lab"
    assert _doc_bucket("Chest X-Ray") == "imaging"
    assert _doc_bucket("MRI Brain") == "imaging"
    assert _doc_bucket("Rx from Dr Rao") == "prescription"
    assert _doc_bucket("Discharge Summary") == "discharge"
    assert _doc_bucket("Ayushman card") == "insurance"
    assert _doc_bucket("something odd") == "other"


def test_bucketing_uses_whole_words_not_substrings():
    # "Latest X-ray" must be imaging, not lab — even though "latest" contains
    # "test". "Contract" must not become imaging via the "ct" keyword.
    assert _doc_bucket("Latest X-ray") == "imaging"
    assert _doc_bucket("Latest scan") == "imaging"
    assert _doc_bucket("Insurance contract") == "insurance"
    assert _doc_bucket("Label copy") == "other"
    # A discharge summary that mentions a blood test buckets as discharge.
    assert _doc_bucket("Discharge summary with blood test") == "discharge"


def test_type_filter_narrows_list(app):
    c, uid = _uid(app, "vault1@medeasy.test")
    with user_context(uid):
        _report(uid, "Blood Test")
        _report(uid, "Chest X-Ray")
        _report(uid, "Prescription")
        labs = list_reports(doc_type="lab")
        imaging = list_reports(doc_type="imaging")
        all_ = list_reports()
    assert len(all_) == 3
    assert len(labs) == 1 and labs[0]["doc_bucket"] == "lab"
    assert len(imaging) == 1 and imaging[0]["doc_bucket"] == "imaging"


def test_api_type_filter(app):
    c, uid = _uid(app, "vault2@medeasy.test")
    with user_context(uid):
        _report(uid, "Lipid Profile")
        _report(uid, "Discharge Summary")
    got = c.get("/api/reports?type=lab").get_json()
    assert len(got) == 1 and got[0]["doc_bucket"] == "lab"
    # every report carries its bucket for the UI
    assert all("doc_bucket" in r for r in c.get("/api/reports").get_json())
