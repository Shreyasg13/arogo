"""The first-run 'connect a family member' step is satisfied by an invite OR a
zero-install alert contact — verified through /api/export/counts['family']."""
import pytest

import auth as auth_module
from db.core import init_db
from app import create_app

PW = "fr-pw-12345"


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c


def test_family_count_starts_zero(app):
    c = _reg(app, "fr1@medeasy.test")
    assert c.get("/api/export/counts").get_json()["family"] == 0


def test_alert_contact_satisfies_family_step(app):
    c = _reg(app, "fr2@medeasy.test")
    c.post("/api/family/alert-contacts", json={"name": "Mom", "phone": "+14155550100"})
    assert c.get("/api/export/counts").get_json()["family"] >= 1


def test_family_invite_satisfies_family_step(app):
    c = _reg(app, "fr3@medeasy.test")
    c.post("/api/family", json={"name": "Fam"})               # own a group
    c.post("/api/family/invite", json={"email": "someone@medeasy.test"})
    assert c.get("/api/export/counts").get_json()["family"] >= 1
