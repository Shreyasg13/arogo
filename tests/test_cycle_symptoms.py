"""Cycle symptom + flow logging and the (non-diagnostic) regularity signal.
PCOS-relevant depth on top of the cycle engine — all framed as the user's own
data, never a diagnosis."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.cycle import (log_symptoms, get_symptom_day, get_symptom_summary,
                      log_period_start, get_cycle_summary, clean_symptoms)

PW = "cycsym-pw-12345"


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


def _day(off):
    return (dt.date.today() - dt.timedelta(days=off)).isoformat()


def test_clean_symptoms_filters_vocab():
    assert clean_symptoms(["cramps", "CRAMPS", "unicorn", ""]) == ["cramps"]
    assert clean_symptoms(None) == []


def test_log_and_read_symptoms(app):
    _, uid = _uid(app, "cs1@medeasy.test")
    with user_context(uid):
        log_symptoms(_day(1), symptoms=["cramps", "bloating"], flow="medium")
        d = get_symptom_day(_day(1))
    assert set(d["symptoms"]) == {"cramps", "bloating"}
    assert d["flow"] == "medium"


def test_relogging_replaces(app):
    _, uid = _uid(app, "cs2@medeasy.test")
    with user_context(uid):
        log_symptoms(_day(1), symptoms=["cramps"], flow="heavy")
        log_symptoms(_day(1), symptoms=["headache"], flow="light")
        d = get_symptom_day(_day(1))
    assert d["symptoms"] == ["headache"] and d["flow"] == "light"


def test_empty_day_clears(app):
    _, uid = _uid(app, "cs3@medeasy.test")
    with user_context(uid):
        log_symptoms(_day(1), symptoms=["cramps"])
        log_symptoms(_day(1), symptoms=[], flow=None, notes="")
        d = get_symptom_day(_day(1))
    assert d["symptoms"] == [] and d["flow"] is None


def test_invalid_flow_ignored(app):
    _, uid = _uid(app, "cs4@medeasy.test")
    with user_context(uid):
        d = log_symptoms(_day(1), symptoms=["acne"], flow="tsunami")
    assert d["flow"] is None and d["symptoms"] == ["acne"]


def test_summary_counts_most_common(app):
    _, uid = _uid(app, "cs5@medeasy.test")
    with user_context(uid):
        log_symptoms(_day(1), symptoms=["cramps", "fatigue"])
        log_symptoms(_day(2), symptoms=["cramps"])
        log_symptoms(_day(3), symptoms=["cramps", "acne"])
        s = get_symptom_summary()
    assert s["has_data"] is True
    assert s["top"][0]["key"] == "cramps" and s["top"][0]["count"] == 3


def test_regularity_flags_irregular_cycles(app):
    _, uid = _uid(app, "cs6@medeasy.test")
    with user_context(uid):
        # starts at 0, 25, 70 days ago → gaps 25 and 45 → spread 20 (irregular)
        log_period_start(_day(70))
        log_period_start(_day(45))
        log_period_start(_day(0))
        s = get_cycle_summary()
    reg = s["regularity"]
    assert reg is not None
    assert reg["irregular"] is True
    assert reg["spread"] == 20


def test_regularity_none_with_few_cycles(app):
    _, uid = _uid(app, "cs7@medeasy.test")
    with user_context(uid):
        log_period_start(_day(28))
        log_period_start(_day(0))   # only one gap → not enough to judge spread
        s = get_cycle_summary()
    assert s["regularity"] is None


def test_api_round_trip(app):
    c, uid = _uid(app, "cs8@medeasy.test")
    r = c.post("/api/cycle/symptoms", json={"date_key": _day(1),
                                            "symptoms": ["cramps"], "flow": "light"})
    assert r.status_code == 200 and r.get_json()["day"]["symptoms"] == ["cramps"]
    assert c.get(f"/api/cycle/symptoms/{_day(1)}").get_json()["flow"] == "light"
    assert c.get("/api/cycle/symptoms").get_json()["has_data"] is True
    # symptoms are walled off from managing caregivers via /api/cycle prefix
    assert c.post("/api/cycle/symptoms", json={"date_key": "bad", "symptoms": []}).status_code == 400
