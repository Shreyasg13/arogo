"""Time-limited shareable health snapshots — public, expiring, revocable, and
strictly limited to a safe subset (never journal/cycle/mood)."""
import datetime as dt
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db.shares import create_snapshot, list_snapshots, revoke_snapshot, resolve_snapshot

PW = "sh-pw-123456"


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


def test_create_and_public_page_renders_meds(app):
    c, uid = _uid(app, "sh1@medeasy.test")
    c.post("/api/medicines", json={"name": "Metformin", "dosage": "500", "unit": "mg",
                                   "frequency": "twice_daily", "times": ["09:00", "21:00"]})
    snap = c.post("/api/share/snapshot", json={"label": "For Dr Rao"}).get_json()["snapshot"]
    assert snap["status"] == "active" and snap["token"]
    assert "user_id" not in snap                       # owner id never leaked to client

    page = c.get(f"/share/{snap['token']}")            # public path works even in same client
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Metformin" in body
    assert page.headers.get("Cache-Control", "").startswith("no-store")
    assert "noindex" in page.headers.get("X-Robots-Tag", "")


def test_public_page_excludes_private_categories(app):
    c, uid = _uid(app, "sh2@medeasy.test")
    with user_context(uid):
        from db.wellness import save_thought
        from db.cycle import log_period_start
        save_thought("SECRETJOURNAL feeling anxious", "low", dt.date.today().isoformat())
        log_period_start((dt.date.today() - dt.timedelta(days=2)).isoformat())
        s = create_snapshot(label="x")
    body = c.get(f"/share/{s['token']}").get_data(as_text=True)
    # The private-walled CONTENT must never appear (the footer disclaimer does
    # name the categories in prose — that's the promise, not a leak).
    assert "SECRETJOURNAL" not in body                       # journal text
    assert "anxious" not in body                             # journal/mood detail
    period_date = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    assert period_date not in body                           # cycle start date


def test_revoked_link_is_gone(app):
    c, uid = _uid(app, "sh3@medeasy.test")
    snap = c.post("/api/share/snapshot", json={}).get_json()["snapshot"]
    assert c.post(f"/api/share/snapshot/{snap['id']}/revoke").status_code == 200
    page = c.get(f"/share/{snap['token']}")
    assert page.status_code == 410
    assert "Metformin" not in page.get_data(as_text=True)


def test_expired_link_is_gone(app):
    c, uid = _uid(app, "sh4@medeasy.test")
    snap = c.post("/api/share/snapshot", json={}).get_json()["snapshot"]
    past = (dt.datetime.utcnow() - dt.timedelta(days=1)).isoformat()
    execute("UPDATE share_snapshots SET expires_at=? WHERE id=?", (past, snap["id"]), commit=True)
    assert c.get(f"/share/{snap['token']}").status_code == 410
    with user_context(uid):
        assert resolve_snapshot(snap["token"]) is None      # fails closed


def test_bad_token_is_gone_not_500(app):
    c, _ = _uid(app, "sh5@medeasy.test")
    assert c.get("/share/nope").status_code == 410
    assert c.get("/share/" + "z" * 40).status_code == 410


def test_snapshots_are_user_scoped(app):
    ca, uid_a = _uid(app, "sh6@medeasy.test")
    cb, uid_b = _uid(app, "sh7@medeasy.test")
    snap_a = ca.post("/api/share/snapshot", json={}).get_json()["snapshot"]
    # B cannot see A's snapshot in their list
    assert cb.get("/api/share/snapshots").get_json()["snapshots"] == []
    # B revoking A's id is a no-op (scoped by user_id); A's link still works
    cb.post(f"/api/share/snapshot/{snap_a['id']}/revoke")
    assert ca.get(f"/share/{snap_a['token']}").status_code == 200


def test_expiry_clamped(app):
    _, uid = _uid(app, "sh8@medeasy.test")
    with user_context(uid):
        s = create_snapshot(days_valid=9999)
        exp = dt.datetime.fromisoformat(s["expires_at"])
        assert exp <= dt.datetime.utcnow() + dt.timedelta(days=90, minutes=1)
