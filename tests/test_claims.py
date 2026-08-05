"""Insurance-claims tracker — lifecycle status, reimbursed vs claimed kept
honest, per-user isolation."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.claims import create_claim, update_claim, delete_claim, list_claims

PW = "clm-pw-123456"


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


def test_create_defaults_and_outstanding(app):
    _, uid = _uid(app, "clm1@medeasy.test")
    with user_context(uid):
        c = create_claim({"insurer": "Star Health", "amount": 12400})
    assert c["status"] == "submitted" and c["pending"] is True
    assert c["reimbursed"] == 0 and c["outstanding"] == 12400


def test_requires_insurer_and_amount(app):
    _, uid = _uid(app, "clm2@medeasy.test")
    with user_context(uid):
        with pytest.raises(ValueError):
            create_claim({"amount": 1000})
        with pytest.raises(ValueError):
            create_claim({"insurer": "X", "amount": 0})
        with pytest.raises(ValueError):
            create_claim({"insurer": "X", "amount": "abc"})


def test_bad_status_defaults_to_submitted(app):
    _, uid = _uid(app, "clm3@medeasy.test")
    with user_context(uid):
        c = create_claim({"insurer": "X", "amount": 100, "status": "totally_made_up"})
    assert c["status"] == "submitted"


def test_partial_payment_outstanding(app):
    _, uid = _uid(app, "clm4@medeasy.test")
    with user_context(uid):
        c = create_claim({"insurer": "X", "amount": 10000})
        upd = update_claim(c["id"], {"status": "partially_paid", "reimbursed": 6000})
    assert upd["reimbursed"] == 6000 and upd["outstanding"] == 4000
    assert upd["pending"] is False       # partially_paid is terminal, not awaiting


def test_summary_awaiting_excludes_terminal(app):
    _, uid = _uid(app, "clm5@medeasy.test")
    with user_context(uid):
        create_claim({"insurer": "A", "amount": 5000})                              # submitted → awaiting 5000
        c2 = create_claim({"insurer": "B", "amount": 8000})
        update_claim(c2["id"], {"status": "paid", "reimbursed": 8000})              # paid → 0 outstanding
        c3 = create_claim({"insurer": "C", "amount": 3000})
        update_claim(c3["id"], {"status": "rejected"})                              # rejected → NOT awaiting
        s = list_claims()["summary"]
    assert s["total_claimed"] == 16000 and s["total_reimbursed"] == 8000
    assert s["awaiting"] == 5000 and s["pending_count"] == 1


def test_negative_reimbursed_floored(app):
    _, uid = _uid(app, "clm6@medeasy.test")
    with user_context(uid):
        c = create_claim({"insurer": "X", "amount": 500, "reimbursed": -50})
    assert c["reimbursed"] == 0


def test_isolation(app):
    _, uid_a = _uid(app, "clm7@medeasy.test")
    _, uid_b = _uid(app, "clm8@medeasy.test")
    with user_context(uid_a):
        create_claim({"insurer": "SecretInsurer", "amount": 100})
    with user_context(uid_b):
        assert list_claims()["claims"] == []


def test_api_round_trip(app):
    c, uid = _uid(app, "clm9@medeasy.test")
    r = c.post("/api/claims", json={"insurer": "Star", "amount": 9000})
    assert r.status_code == 200
    cid = r.get_json()["claim"]["id"]
    assert c.get("/api/claims").get_json()["summary"]["awaiting"] == 9000
    upd = c.patch(f"/api/claims/{cid}", json={"status": "paid", "reimbursed": 9000}).get_json()["claim"]
    assert upd["status"] == "paid" and upd["outstanding"] == 0
    assert c.get("/api/claims").get_json()["summary"]["awaiting"] == 0
    assert c.delete(f"/api/claims/{cid}").get_json()["success"] is True
    assert c.post("/api/claims", json={"insurer": ""}).status_code == 400
