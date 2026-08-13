"""J2 — peak-flow tracker. PEF readings zoned green/yellow/red against the user's
OWN personal best (asthma-action-plan traffic lights). From the user's own
readings in the vitals table; no clinical claim."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.health import log_vital
from db.peak_flow import get_peak_flow_state

PW = "pf-pw-1234567"


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


def test_empty(app):
    _, uid = _uid(app, "pf1@medeasy.test")
    with user_context(uid):
        d = get_peak_flow_state()
    assert d["has_data"] is False and d["personal_best"] is None


def test_zones_are_relative_to_personal_best(app):
    _, uid = _uid(app, "pf2@medeasy.test")
    with user_context(uid):
        log_vital({"type": "peak_flow", "value1": 500, "date_key": "2026-08-01"})  # personal best
        log_vital({"type": "peak_flow", "value1": 450, "date_key": "2026-08-02"})  # 90% → green
        log_vital({"type": "peak_flow", "value1": 300, "date_key": "2026-08-03"})  # 60% → yellow
        log_vital({"type": "peak_flow", "value1": 200, "date_key": "2026-08-04"})  # 40% → red
        d = get_peak_flow_state()
    assert d["personal_best"] == 500
    assert d["green_min"] == 400 and d["yellow_min"] == 250
    zones = {r["value"]: r["zone"] for r in d["readings"]}
    assert zones[500] == "green" and zones[450] == "green"
    assert zones[300] == "yellow" and zones[200] == "red"


def test_latest_is_newest(app):
    _, uid = _uid(app, "pf3@medeasy.test")
    with user_context(uid):
        log_vital({"type": "peak_flow", "value1": 480, "date_key": "2026-08-01"})
        log_vital({"type": "peak_flow", "value1": 460, "date_key": "2026-08-10"})
        d = get_peak_flow_state()
    assert d["latest"]["value"] == 460          # get_vitals returns newest first
    assert d["latest"]["pct_of_best"] == 96     # 460/480


def test_out_of_range_reading_rejected(app):
    _, uid = _uid(app, "pf4@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            log_vital({"type": "peak_flow", "value1": 5000})   # beyond the 30–900 guard


def test_api(app):
    c, uid = _uid(app, "pf5@medeasy.test")
    c.post("/api/vitals", json={"type": "peak_flow", "value1": 400})
    body = c.get("/api/peak-flow").get_json()
    assert body["has_data"] is True and body["personal_best"] == 400
