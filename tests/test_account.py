"""Tests for self-serve data export and account deletion (DPDP/GDPR)."""
import json

import pytest

import auth as auth_module
from db.core import init_db
from app import create_app

PW = "acct-pw-12345"


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


def test_export_returns_own_data_without_secrets(app):
    c = _reg(app, "exp1@medeasy.test")
    c.post("/api/medicines", json={"name": "Metformin", "dosage": "500"})
    c.post("/api/food/log", json={
        "food_id": "roti", "food_name": "Roti", "meal_type": "lunch",
        "date_key": "2026-07-26", "quantity_g": 40, "calories": 120})

    r = c.get("/api/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.get_data(as_text=True))

    assert data["account"]["email"] == "exp1@medeasy.test"
    assert "password_hash" not in data["account"]      # never export the hash
    assert any(m["name"] == "Metformin" for m in data.get("medicines", []))
    assert len(data.get("food_logs", [])) >= 1


def test_export_is_isolated_per_user(app):
    a = _reg(app, "exp2a@medeasy.test")
    b = _reg(app, "exp2b@medeasy.test")
    a.post("/api/medicines", json={"name": "OnlyMineMed", "dosage": "1"})
    data = json.loads(b.get("/api/account/export").get_data(as_text=True))
    assert not any(m["name"] == "OnlyMineMed" for m in data.get("medicines", []))


def test_delete_requires_correct_password(app):
    c = _reg(app, "del1@medeasy.test")
    assert c.delete("/api/account", json={"password": "wrong"}).status_code == 401


def test_delete_removes_account_and_data(app):
    email = "del2@medeasy.test"
    c = _reg(app, email)
    c.post("/api/medicines", json={"name": "DeleteMe", "dosage": "1"})
    assert c.delete("/api/account", json={"password": PW}).status_code == 200

    # the account is gone — a fresh client can no longer sign in
    c2 = app.test_client()
    assert c2.post("/auth/login", json={"email": email, "password": PW}).status_code == 401
