"""My care team — provider directory CRUD, per-user isolation, appointment unlink."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.providers import create_provider, update_provider, delete_provider, list_providers

PW = "prov-pw-12345"


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


def test_create_and_list_sorted(app):
    _, uid = _uid(app, "prov1@medeasy.test")
    with user_context(uid):
        create_provider({"name": "Dr Zara", "specialty": "Cardiology", "phone": "+91 90000 11111"})
        create_provider({"name": "dr Anand", "specialty": "GP"})
        names = [p["name"] for p in list_providers()]
    assert names == ["dr Anand", "Dr Zara"]        # case-insensitive sort


def test_name_required(app):
    _, uid = _uid(app, "prov2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_provider({"specialty": "GP"})


def test_update(app):
    _, uid = _uid(app, "prov3@medeasy.test")
    with user_context(uid):
        p = create_provider({"name": "Dr Rao"})
        upd = update_provider(p["id"], {"phone": "+91 22 1234", "clinic": "City Clinic"})
    assert upd["phone"] == "+91 22 1234" and upd["clinic"] == "City Clinic" and upd["name"] == "Dr Rao"


def test_delete_unlinks_appointments(app):
    _, uid = _uid(app, "prov4@medeasy.test")
    with user_context(uid):
        p = create_provider({"name": "Dr Linked"})
        execute("""INSERT INTO appointments (id,user_id,title,date,provider_id,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), uid, "Checkup", "2026-09-01", p["id"], now_iso()), commit=True)
        delete_provider(p["id"])
        appt = execute("SELECT provider_id FROM appointments WHERE user_id=? AND title='Checkup'",
                       (uid,), fetchone=True)
    assert appt["provider_id"] is None            # appointment survives, link cleared
    with user_context(uid):
        assert list_providers() == []


def test_isolation(app):
    _, uid_a = _uid(app, "prov5@medeasy.test")
    _, uid_b = _uid(app, "prov6@medeasy.test")
    with user_context(uid_a):
        create_provider({"name": "SecretDoc"})
    with user_context(uid_b):
        assert all(p["name"] != "SecretDoc" for p in list_providers())
        # B cannot update/delete A's provider
        pa = execute("SELECT id FROM providers WHERE name='SecretDoc'", fetchone=True)["id"]
        with pytest.raises(ValueError):
            update_provider(pa, {"name": "hacked"})


def test_api_round_trip(app):
    c, uid = _uid(app, "prov7@medeasy.test")
    r = c.post("/api/providers", json={"name": "Dr API", "specialty": "Derm", "phone": "123"})
    assert r.status_code == 200
    pid = r.get_json()["provider"]["id"]
    assert c.get("/api/providers").get_json()["providers"][0]["name"] == "Dr API"
    assert c.patch(f"/api/providers/{pid}", json={"specialty": "Dermatology"}).get_json()["provider"]["specialty"] == "Dermatology"
    assert c.delete(f"/api/providers/{pid}").get_json()["success"] is True
    assert c.get("/api/providers").get_json()["providers"] == []
    assert c.post("/api/providers", json={"name": ""}).status_code == 400
