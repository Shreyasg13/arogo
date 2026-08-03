"""Refill management: order state, restock clears it, pharmacy note, and the
low-stock reminder gating. Running out of pills is a top cause of missed doses,
so this loop is worth locking down."""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

PW = "refill-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "refill@medeasy.test", "password": PW})
    return c


def _new_low_med(client):
    """A once-daily medicine with 2 pills → 2 days left, under the 7-day threshold."""
    r = client.post("/api/medicines", json={
        "name": "Metformin", "dosage": "500", "unit": "mg",
        "frequency": "once_daily", "times": ["09:00"]})
    mid = r.get_json()["medicine"]["id"]
    client.post(f"/api/medicines/{mid}/stock",
                json={"pill_count": 2, "pills_per_dose": 1, "refill_threshold": 7})
    return mid


def _low(client):
    return {m["id"]: m for m in client.get("/api/medicines/low-stock").get_json()}


def test_low_stock_detects_and_starts_unordered(client):
    mid = _new_low_med(client)
    low = _low(client)
    assert mid in low
    assert low[mid]["days_left"] == 2
    assert (low[mid].get("refill_status") or None) is None


def test_order_then_restock_clears_it(client):
    mid = _new_low_med(client)
    # Order → flagged
    r = client.post(f"/api/medicines/{mid}/refill/ordered")
    assert r.status_code == 200 and r.get_json()["medicine"]["refill_status"] == "ordered"
    assert _low(client)[mid]["refill_status"] == "ordered"     # still low, but on the way
    # Picked up (restock to a full pack, count goes up) → flag clears
    client.post(f"/api/medicines/{mid}/stock",
                json={"pill_count": 60, "pills_per_dose": 1, "refill_threshold": 7})
    assert mid not in _low(client)                             # 60 days left, no longer low
    m = {x["id"]: x for x in client.get("/api/medicines").get_json()}[mid]
    assert (m.get("refill_status") or None) is None


def test_threshold_edit_does_not_clear_ordered(client):
    mid = _new_low_med(client)
    client.post(f"/api/medicines/{mid}/refill/ordered")
    # Editing the threshold (count unchanged) must NOT cancel the pending order.
    client.post(f"/api/medicines/{mid}/stock",
                json={"pill_count": 2, "pills_per_dose": 1, "refill_threshold": 10})
    assert _low(client)[mid]["refill_status"] == "ordered"


def test_pharmacy_note_persists(client):
    mid = _new_low_med(client)
    r = client.post(f"/api/medicines/{mid}/refill/note",
                    json={"pharmacy_note": "Apollo near home"})
    assert r.status_code == 200 and r.get_json()["medicine"]["pharmacy_note"] == "Apollo near home"
    assert _low(client)[mid]["pharmacy_note"] == "Apollo near home"


def test_refill_reminder_gates_on_ordered(app, monkeypatch):
    # The scheduler job should push for a low, un-ordered med — and go quiet
    # once it's marked ordered. Fresh user so no other low meds leak in.
    import scheduler, push
    from db.core import execute
    client = app.test_client()
    client.post("/auth/register", json={"email": "refill2@medeasy.test", "password": PW})
    mid = _new_low_med(client)
    uid = execute("SELECT user_id FROM medicines WHERE id=?", (mid,), fetchone=True)["user_id"]
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id, endpoint, user_id, sub_json, created_at) VALUES (?,?,?,?,?)",
            ("s-refill", "https://push.test/refill-ep", uid, "{}", "2026-01-01"), commit=True)
    execute("DELETE FROM notification_log WHERE user_id=?", (uid,), commit=True)
    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user", lambda u, t, b, *a, **k: (sent.append((u, t)) or 1))

    scheduler._refill_reminders()
    assert any(mid in t or "Refill" in t for _, t in sent), "no refill reminder for a low med"

    # Once ordered, a fresh run must NOT nudge again.
    client.post(f"/api/medicines/{mid}/refill/ordered")
    # Pass the LIKE pattern as a parameter — a literal % in the SQL string breaks
    # under psycopg2's %-formatting (the whole reason we run this suite on PG too).
    execute("DELETE FROM notification_log WHERE user_id=? AND source_id LIKE ?", (uid, 'refill:%'), commit=True)
    sent.clear()
    scheduler._refill_reminders()
    assert sent == [], "reminder fired even though the refill was ordered"
