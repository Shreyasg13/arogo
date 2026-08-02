"""Doctor-visit prep questions: jot, tick off, and carry to the summary."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "dq-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def test_add_list_toggle_delete(app):
    c = _register(app, "dq1@medeasy.test")
    q = c.post("/api/doctor-questions", json={"question": "Should I keep the evening dose?"}).get_json()["question"]
    assert q["asked"] == 0
    got = c.get("/api/doctor-questions").get_json()["questions"]
    assert [x["question"] for x in got] == ["Should I keep the evening dose?"]

    c.post(f"/api/doctor-questions/{q['id']}/toggle")
    assert c.get("/api/doctor-questions").get_json()["questions"][0]["asked"] == 1
    c.post(f"/api/doctor-questions/{q['id']}/toggle")
    assert c.get("/api/doctor-questions").get_json()["questions"][0]["asked"] == 0

    c.delete(f"/api/doctor-questions/{q['id']}")
    assert c.get("/api/doctor-questions").get_json()["questions"] == []


def test_blank_question_is_rejected(app):
    c = _register(app, "dq2@medeasy.test")
    r = c.post("/api/doctor-questions", json={"question": "   "})
    assert r.status_code == 400 and r.get_json()["success"] is False


def test_only_unasked_questions_reach_the_doctor_summary(app):
    c = _register(app, "dq3@medeasy.test")
    open_q = c.post("/api/doctor-questions", json={"question": "New pill side effects?"}).get_json()["question"]
    done_q = c.post("/api/doctor-questions", json={"question": "Already discussed BP"}).get_json()["question"]
    c.post(f"/api/doctor-questions/{done_q['id']}/toggle")     # mark asked → excluded

    summary = c.get("/api/doctor-summary").get_json()
    assert summary["questions"] == ["New pill side effects?"]


def test_doctor_questions_require_auth(app):
    assert app.test_client().get("/api/doctor-questions").status_code == 401
