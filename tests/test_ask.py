"""Ask-your-health — a private, deterministic Q&A over the user's own data.

Guards: it answers only from real logs, never fabricates, says so when it can't,
and is walled from a caregiver acting-as.
"""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso, user_today
from db.ask import answer_question

PW = "ask-pw-12345"


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


def _days_ago(n):
    return (dt.date.fromisoformat(user_today()) - dt.timedelta(days=n)).isoformat()


def test_gibberish_is_honestly_declined(app):
    _, uid = _uid(app, "ask1@medeasy.test")
    with user_context(uid):
        r = answer_question("what is the meaning of life")
    assert r["matched"] is False
    assert "only answer from what you've logged" in r["answer"]
    assert r["suggestions"]


def test_empty_question(app):
    _, uid = _uid(app, "ask2@medeasy.test")
    with user_context(uid):
        r = answer_question("")
    assert r["matched"] is False and r["suggestions"]


def test_last_logged_uses_real_dates(app):
    _, uid = _uid(app, "ask3@medeasy.test")
    with user_context(uid):
        execute("INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id) VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), _days_ago(2), "blood_pressure", 120, 80, "mmHg", now_iso(), uid), commit=True)
        r = answer_question("when did I last log my blood pressure?")
    assert r["matched"] and r["kind"] == "last"
    assert _days_ago(2) in r["answer"] and "2 days ago" in r["answer"]


def test_last_logged_when_never(app):
    _, uid = _uid(app, "ask4@medeasy.test")
    with user_context(uid):
        r = answer_question("when did I last check my weight")
    assert r["matched"] and "don't have any weight logged" in r["answer"]


def test_average_never_judges(app):
    _, uid = _uid(app, "ask5@medeasy.test")
    with user_context(uid):
        for v in (118, 122, 120):
            execute("INSERT INTO vitals (id,date_key,type,value1,value2,unit,logged_at,user_id) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id(), _days_ago(3), "blood_pressure", v, 78, "mmHg", now_iso(), uid), commit=True)
        r = answer_question("what's my average blood pressure")
    assert r["matched"] and r["kind"] == "average"
    assert "120/78" in r["answer"] and "3 readings" in r["answer"]
    # honesty: no verdict words
    assert not any(w in r["answer"].lower() for w in ("high", "low", "normal", "good", "bad"))


def test_next_appointment(app):
    _, uid = _uid(app, "ask6@medeasy.test")
    fut = (dt.date.fromisoformat(user_today()) + dt.timedelta(days=5)).isoformat()
    with user_context(uid):
        execute("INSERT INTO appointments (id,user_id,title,kind,date,time,created_at) VALUES (?,?,?,?,?,?,?)",
                (new_id(), uid, "Cardiology", "doctor", fut, "10:00", now_iso()), commit=True)
        r = answer_question("when is my next appointment?")
    assert r["matched"] and "Cardiology" in r["answer"] and fut in r["answer"]


def test_meds_list(app):
    _, uid = _uid(app, "ask7@medeasy.test")
    with user_context(uid):
        execute("INSERT INTO medicines (id,name,active,created_at,user_id) VALUES (?,?,?,?,?)",
                (new_id(), "Metformin", 1, now_iso(), uid), commit=True)
        r = answer_question("what medicines am I taking")
    assert r["matched"] and "Metformin" in r["answer"]


def test_route_and_acting_as_wall(app):
    c, _ = _uid(app, "ask8@medeasy.test")
    assert c.get("/api/ask?q=when is my next appointment").status_code == 200
    # unauth
    assert app.test_client().get("/api/ask?q=x").status_code in (401, 403)


def test_wall_listed_in_acting_as_private():
    assert '/api/ask' in auth_module._ACTING_AS_PRIVATE
