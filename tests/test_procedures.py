"""O1 procedures & hospitalizations — dated facts about past surgeries, stays and
procedures. User-scoped; nothing interpreted."""
import pytest
import auth as auth_module
from app import create_app
from db.core import init_db

PW = "proc-pw-1234567"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client(); c.post("/auth/register", json={"email": email, "password": PW}); return c


def test_add_list_and_kind_default(app):
    c = _reg(app, "proc1@medeasy.test")
    c.post("/api/procedures", json={"kind": "surgery", "name": "Appendectomy", "date_key": "2019-05-10", "provider": "City Hospital"})
    c.post("/api/procedures", json={"name": "MRI knee", "date_key": "2024-01-02"})   # kind defaults
    procs = c.get("/api/procedures").get_json()["procedures"]
    assert len(procs) == 2
    assert procs[0]["date_key"] == "2024-01-02" and procs[0]["kind"] == "procedure"   # newest first


def test_name_and_date_required(app):
    c = _reg(app, "proc2@medeasy.test")
    assert c.post("/api/procedures", json={"name": "", "date_key": "2020-01-01"}).status_code == 400
    assert c.post("/api/procedures", json={"name": "X", "date_key": "nope"}).status_code == 400
    assert c.post("/api/procedures", json={"name": "X", "date_key": "2020-01-01", "end_date": "bad"}).status_code == 400


def test_user_scoped(app):
    a = _reg(app, "proc3a@medeasy.test"); b = _reg(app, "proc3b@medeasy.test")
    p = a.post("/api/procedures", json={"name": "Private op", "date_key": "2021-01-01"}).get_json()["procedure"]
    assert b.get("/api/procedures").get_json()["procedures"] == []
    b.delete(f"/api/procedures/{p['id']}")
    assert len(a.get("/api/procedures").get_json()["procedures"]) == 1


def test_requires_auth(app):
    assert app.test_client().get("/api/procedures").status_code in (401, 403)
