"""Cross-factor symptom correlations — patterns (never causes) against sleep,
medicine start, and the menstrual cycle."""
import datetime as _dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.symptom_insights import get_symptom_correlations

PW = "sym-pw-123456"


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


def _ago(n):
    return (_dt.date.today() - _dt.timedelta(days=n)).isoformat()


def _symptom(uid, name, dkey, sev=5):
    execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,notes,logged_at,user_id)
               VALUES (?,?,?,?,'evening','',?,?)""", (new_id(), name, sev, dkey, now_iso(), uid), commit=True)


def _sleep(uid, dkey, hours):
    execute("""INSERT INTO sleep_logs (id,date_key,bedtime,wake_time,duration_h,quality,notes,created_at,user_id)
               VALUES (?,?,'23:00','07:00',?,3,'',?,?)""", (new_id(), dkey, hours, now_iso(), uid), commit=True)


def _cycle(uid, start, end):
    execute("""INSERT INTO menstrual_cycles (id,start_date,end_date,notes,created_at,user_id)
               VALUES (?,?,?,'',?,?)""", (new_id(), start, end, now_iso(), uid), commit=True)


def _find(res, typ, symptom):
    return next((f for f in res["findings"] if f["type"] == typ and f["symptom"] == symptom), None)


def test_sleep_correlation(app):
    _, uid = _uid(app, "sym1@medeasy.test")
    with user_context(uid):
        for n in (20, 18, 16, 14):          # symptom days, short sleep
            _symptom(uid, "Headache", _ago(n)); _sleep(uid, _ago(n), 5.0)
        for n in (19, 17, 15, 13):          # other days, good sleep
            _sleep(uid, _ago(n), 8.0)
        res = get_symptom_correlations(days=40)
    f = _find(res, "sleep", "Headache")
    assert f is not None
    assert f["symptom_avg"] == 5.0 and f["other_avg"] == 8.0
    assert f["under6_days"] == 4 and f["total_days"] == 4


def test_no_sleep_finding_when_gap_small(app):
    _, uid = _uid(app, "sym2@medeasy.test")
    with user_context(uid):
        for n in (20, 18, 16):
            _symptom(uid, "Fatigue", _ago(n)); _sleep(uid, _ago(n), 7.2)
        for n in (19, 17, 15):
            _sleep(uid, _ago(n), 7.4)       # near-identical → no pattern
        res = get_symptom_correlations(days=40)
    assert _find(res, "sleep", "Fatigue") is None


def test_med_start_timing(app):
    c, uid = _uid(app, "sym3@medeasy.test")
    c.post("/api/medicines", json={"name": "Sertraline", "frequency": "once_daily",
                                   "times": ["09:00"], "start_date": _ago(20)})
    with user_context(uid):
        for n in (15, 14, 13):              # first appears 5 days after starting
            _symptom(uid, "Nausea", _ago(n))
        res = get_symptom_correlations(days=40)
    f = _find(res, "med_start", "Nausea")
    assert f is not None and f["medicine"] == "Sertraline" and f["days_after"] == 5


def test_cycle_correlation(app):
    _, uid = _uid(app, "sym4@medeasy.test")
    with user_context(uid):
        _cycle(uid, _ago(10), _ago(6))      # period spans day-10..day-6
        for n in (10, 9, 8):                # cramps during the period
            _symptom(uid, "Cramps", _ago(n))
        res = get_symptom_correlations(days=40)
    f = _find(res, "cycle", "Cramps")
    assert f is not None and f["phase"] == "period" and f["count"] == 3


def test_min_occurrences_gate(app):
    _, uid = _uid(app, "sym5@medeasy.test")
    with user_context(uid):
        _symptom(uid, "Dizzy", _ago(10)); _sleep(uid, _ago(10), 4.0)
        _symptom(uid, "Dizzy", _ago(9));  _sleep(uid, _ago(9), 4.0)   # only 2 → too few
        for n in (8, 7, 6, 5):
            _sleep(uid, _ago(n), 8.0)
        res = get_symptom_correlations(days=40)
    assert _find(res, "sleep", "Dizzy") is None
    assert res["analysed"] == 0


def test_api_endpoint(app):
    c, uid = _uid(app, "sym6@medeasy.test")
    with user_context(uid):
        for n in (12, 11, 10):
            _symptom(uid, "Ache", _ago(n)); _sleep(uid, _ago(n), 5.0)
        for n in (9, 8, 7):
            _sleep(uid, _ago(n), 8.0)
    r = c.get("/api/symptoms/correlations")
    assert r.status_code == 200
    body = r.get_json()
    assert "findings" in body and body["cycle_private"] is False
