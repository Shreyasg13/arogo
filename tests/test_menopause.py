"""O3 menopause companion — dated 0-3 symptom log + a descriptive frequency
summary. No staging, diagnosis or advice."""
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db

PW = "meno-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client(); c.post("/auth/register", json={"email": email, "password": PW}); return c


def test_log_and_summary(app):
    c = _reg(app, "meno1@medeasy.test")
    c.post("/api/menopause", json={"date_key": "2026-08-10", "hot_flashes": 3, "sleep": 2, "mood": 1})
    c.post("/api/menopause", json={"date_key": "2026-08-11", "hot_flashes": 2, "sleep": 0, "mood": 0})
    d = c.get("/api/menopause").get_json()
    assert len(d["logs"]) == 2 and d["summary"]["has_data"] is True
    hf = d["summary"]["symptoms"]["hot_flashes"]
    assert hf["flare_days"] == 2 and hf["avg_when_present"] == 2.5     # (3+2)/2


def test_severity_clamped(app):
    c = _reg(app, "meno2@medeasy.test")
    log = c.post("/api/menopause", json={"date_key": "2026-08-01", "hot_flashes": 9}).get_json()["log"]
    assert log["hot_flashes"] == 3       # clamped to 0-3


def test_empty_summary_has_no_fabricated_findings(app):
    c = _reg(app, "meno3@medeasy.test")
    s = c.get("/api/menopause").get_json()["summary"]
    assert s["has_data"] is False
    assert s["symptoms"]["mood"]["avg_when_present"] is None     # not a fake 0


def test_user_scoped_and_delete(app):
    a = _reg(app, "meno4a@medeasy.test"); b = _reg(app, "meno4b@medeasy.test")
    log = a.post("/api/menopause", json={"date_key": "2026-08-05", "mood": 2}).get_json()["log"]
    assert b.get("/api/menopause").get_json()["logs"] == []
    b.delete(f"/api/menopause/{log['id']}")
    assert len(a.get("/api/menopause").get_json()["logs"]) == 1


def test_requires_auth(app):
    assert app.test_client().get("/api/menopause").status_code in (401, 403)
