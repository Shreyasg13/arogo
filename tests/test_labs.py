"""Lab-panel results: logging, reference-range status (honest, non-diagnostic),
trends, and sex-aware ranges."""
import pytest

import auth as auth_module
import lab_catalog
from app import create_app
from db.core import init_db, user_context, execute
from db.labs import log_lab_result, get_latest_by_test, get_lab_trend, delete_lab_result

PW = "labs-pw-12345"


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


def test_catalog_status_thresholds():
    assert lab_catalog.status_for("hba1c", 5.2) == "in_range"
    assert lab_catalog.status_for("hba1c", 7.0) == "high"
    assert lab_catalog.status_for("vitamin_d", 12) == "low"
    assert lab_catalog.status_for("unknown_test", 5) is None


def test_sex_aware_range():
    # Haemoglobin 12.5: normal for a woman, low for the male/general range.
    assert lab_catalog.status_for("hemoglobin", 12.5, "female") == "in_range"
    assert lab_catalog.status_for("hemoglobin", 12.5, "male") == "low"


def test_log_and_decorate(app):
    c, uid = _uid(app, "lab1@medeasy.test")
    with user_context(uid):
        r = log_lab_result("hba1c", 6.8, "2026-07-01")
        assert r["status"] == "high" and r["ref_high"] == 5.6
        latest = get_latest_by_test()
    assert len(latest) == 1
    assert latest[0]["lab_key"] == "hba1c" and latest[0]["category"] == "Diabetes"


def test_latest_per_test_dedupes(app):
    c, uid = _uid(app, "lab2@medeasy.test")
    with user_context(uid):
        log_lab_result("hba1c", 8.0, "2026-05-01")
        log_lab_result("hba1c", 6.5, "2026-07-01")   # newer
        latest = get_latest_by_test()
    assert len(latest) == 1 and latest[0]["value"] == 6.5   # newest wins


def test_trend_orders_oldest_to_newest(app):
    c, uid = _uid(app, "lab3@medeasy.test")
    with user_context(uid):
        log_lab_result("tsh", 6.0, "2026-03-01")
        log_lab_result("tsh", 3.2, "2026-07-01")
        t = get_lab_trend("tsh")
    assert [p["value"] for p in t["points"]] == [6.0, 3.2]
    assert t["latest"]["value"] == 3.2
    assert t["ref_low"] == 0.4 and t["ref_high"] == 4.0


def test_freeform_test_is_loggable_without_range(app):
    c, uid = _uid(app, "lab4@medeasy.test")
    with user_context(uid):
        r = log_lab_result("CRP", 3.0, "2026-07-01")
    assert r["status"] is None and r["ref_low"] is None   # no catalog range, still stored


def test_rejects_non_numeric(app):
    c, uid = _uid(app, "lab5@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            log_lab_result("hba1c", "abc", "2026-07-01")


def test_api_round_trip(app):
    c, uid = _uid(app, "lab6@medeasy.test")
    r = c.post("/api/labs", json={"lab_key": "ldl", "value": 145, "date_key": "2026-07-01"})
    assert r.status_code == 200 and r.get_json()["result"]["status"] == "high"
    assert c.get("/api/labs").get_json()["results"][0]["lab_key"] == "ldl"
    assert c.get("/api/labs/catalog").get_json()["categories"]
    assert c.get("/api/labs/trend/ldl").get_json()["latest"]["value"] == 145
    # bad value rejected
    assert c.post("/api/labs", json={"lab_key": "ldl", "value": "x", "date_key": "2026-07-01"}).status_code == 400
    # a non-string lab_key (list/dict) must be a clean 400, not a 500
    assert c.post("/api/labs", json={"lab_key": [1, 2], "value": 5, "date_key": "2026-07-01"}).status_code == 400
    assert c.post("/api/labs", json={"lab_key": {}, "value": 5, "date_key": "2026-07-01"}).status_code == 400
