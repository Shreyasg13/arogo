"""Category 1 — device CSV import. Parse a home-device CSV into candidate vitals
(preview never saves), then commit the confirmed rows through log_vital (ranges
enforced, bad rows skipped+counted, user-scoped)."""
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db, execute
from db.vitals_import import parse_vitals_csv

PW = "vimp-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client(); c.post("/auth/register", json={"email": email, "password": PW}); return c


def test_parse_wide_bp_and_sugar():
    csv = "Date,Systolic,Diastolic,Glucose\n2026-08-01,120,80,95\n2026-08-02,130,85,110\n"
    d = parse_vitals_csv(csv)
    assert d["detected"]["shape"] == "wide"
    bps = [c for c in d["candidates"] if c["type"] == "blood_pressure"]
    sugars = [c for c in d["candidates"] if c["type"] == "blood_sugar"]
    assert len(bps) == 2 and bps[0]["value1"] == 120 and bps[0]["value2"] == 80
    assert len(sugars) == 2 and sugars[0]["value1"] == 95


def test_parse_long_format_and_slashed_bp():
    csv = "date,type,value\n2026-08-01,pulse,72\n2026-08-01,bp,118/76\n01/08/2026,spo2,98\n"
    d = parse_vitals_csv(csv)
    assert d["detected"]["shape"] == "long"
    types = {c["type"] for c in d["candidates"]}
    assert types == {"heart_rate", "blood_pressure", "spo2"}
    bp = next(c for c in d["candidates"] if c["type"] == "blood_pressure")
    assert bp["value1"] == 118 and bp["value2"] == 76


def test_bad_dates_and_values_are_skipped_not_invented():
    csv = "Date,Glucose\nnot-a-date,95\n2026-08-01,abc\n2026-08-02,105\n"
    d = parse_vitals_csv(csv)
    assert len(d["candidates"]) == 1 and d["candidates"][0]["value1"] == 105
    assert d["skipped"] == 2


def test_commit_saves_and_range_checks(app):
    c = _reg(app, "vimp1@medeasy.test")
    rows = [
        {"type": "blood_pressure", "value1": 122, "value2": 78, "unit": "mmHg", "date_key": "2026-08-01"},
        {"type": "blood_sugar", "value1": 99, "unit": "mg/dL", "date_key": "2026-08-01"},
        {"type": "blood_sugar", "value1": 99999, "date_key": "2026-08-01"},   # out of range → rejected
        {"type": "weight", "value1": 70, "date_key": "2026-08-01"},           # not an allowed vital type
    ]
    r = c.post("/api/import/vitals/commit", json={"rows": rows}).get_json()
    assert r["saved"] == 2 and r["failed"] == 2
    n = dict(execute("SELECT COUNT(*) c FROM vitals WHERE user_id=(SELECT id FROM users WHERE email='vimp1@medeasy.test')", fetchone=True))["c"]
    assert n == 2


def test_preview_endpoint_saves_nothing(app):
    c = _reg(app, "vimp2@medeasy.test")
    d = c.post("/api/import/vitals/preview", json={"csv": "Date,Systolic,Diastolic\n2026-08-01,120,80\n"}).get_json()
    assert len(d["candidates"]) == 1
    n = dict(execute("SELECT COUNT(*) c FROM vitals WHERE user_id=(SELECT id FROM users WHERE email='vimp2@medeasy.test')", fetchone=True))["c"]
    assert n == 0        # preview never writes


def test_requires_auth(app):
    anon = app.test_client()
    assert anon.post("/api/import/vitals/preview", json={"csv": "x"}).status_code in (401, 403)
    assert anon.post("/api/import/vitals/commit", json={"rows": []}).status_code in (401, 403)
