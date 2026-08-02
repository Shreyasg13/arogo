"""Local backup & restore: full snapshot download + guarded import."""
import json

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "bkp-pw-123456"


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


def test_backup_downloads_a_named_json_snapshot(app):
    c = _register(app, "bkp1@medeasy.test")
    c.post("/api/medicines", json={"name": "Metformin", "frequency": "once_daily", "times": ["09:00"]})
    r = c.get("/api/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.data)
    assert data["_backup"]["app"] == "arogo"
    assert any(m["name"] == "Metformin" for m in data["medicines"])


def test_restore_replaces_current_data_with_the_backup(app):
    c = _register(app, "bkp2@medeasy.test")
    c.post("/api/medicines", json={"name": "Original", "frequency": "once_daily", "times": ["09:00"]})
    backup = json.loads(c.get("/api/backup").data)

    # Change the world after taking the backup…
    c.post("/api/medicines", json={"name": "AddedLater", "frequency": "once_daily", "times": ["10:00"]})
    assert {m["name"] for m in c.get("/api/medicines").get_json()} == {"Original", "AddedLater"}

    # …then restore the backup: only what it held should remain.
    res = c.post("/api/import", json=backup).get_json()
    assert res["success"] is True and res["total"] >= 1
    names = {m["name"] for m in c.get("/api/medicines").get_json()}
    assert names == {"Original"}


def test_restore_rejects_a_file_that_isnt_a_backup(app):
    c = _register(app, "bkp3@medeasy.test")
    r = c.post("/api/import", json={"hello": "world"})
    assert r.status_code == 400 and r.get_json()["success"] is False


def test_restore_forces_ownership_to_the_current_user(app):
    c = _register(app, "bkp4@medeasy.test")
    # A crafted backup claiming rows belong to someone else must still land on me.
    payload = {"medicines": [{
        "id": "x1", "name": "Injected", "frequency": "once_daily",
        "times": '["09:00"]', "active": 1, "created_at": "2026-01-01T00:00:00",
        "user_id": "SOMEONE-ELSE"}]}
    c.post("/api/import", json=payload)
    got = c.get("/api/medicines").get_json()
    assert [m["name"] for m in got] == ["Injected"]     # visible to me = owned by me


def test_backup_and_import_require_auth(app):
    anon = app.test_client()
    assert anon.get("/api/backup").status_code == 401
    assert anon.post("/api/import", json={"medicines": []}).status_code == 401
