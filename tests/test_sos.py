"""Emergency SOS: one-tap alert to caregivers, honest about who was reached."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "sos-pw-1234567"


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


def test_sos_with_no_caregivers_reaches_nobody_and_says_so(app):
    c = _register(app, "sos1@medeasy.test")
    r = c.post("/api/sos", json={}).get_json()
    assert r["success"] is True
    # No caregivers + nothing configured → honest zero, never a fake success.
    assert r["reached"] == 0 and r["who"] == []


def test_sos_logs_a_transparency_note_to_the_members_own_feed(app):
    c = _register(app, "sos2@medeasy.test")
    c.post("/api/sos", json={"note": "chest pain"})
    notes = c.get("/api/notifications").get_json()["notifications"]
    assert any(n["title"] == "SOS sent" for n in notes)


def test_sos_reached_is_always_an_integer(app):
    c = _register(app, "sos3@medeasy.test")
    r = c.post("/api/sos", json={"note": "x" * 500}).get_json()   # over-long note is fine
    assert isinstance(r["reached"], int)


def test_sos_requires_auth(app):
    assert app.test_client().post("/api/sos", json={}).status_code == 401
