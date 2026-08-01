"""'Why I take this' (purpose) + a real dose snooze."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute, user_context

PW = "extra-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "extra@medeasy.test", "password": PW})
    return c


def _add_med(client, **extra):
    body = {"name": "Amlodipine", "dosage": "5", "unit": "mg",
            "frequency": "once_daily", "times": ["09:00"], **extra}
    return client.post("/api/medicines", json=body).get_json()["medicine"]


# ── purpose ──────────────────────────────────────────────────────────────────
def test_purpose_persists_and_flows_to_today_doses(client):
    m = _add_med(client, purpose="blood pressure")
    assert m["purpose"] == "blood pressure"
    doses = client.get("/api/medicines/today").get_json()
    row = next(d for d in doses if d["med_id"] == m["id"])
    assert row["purpose"] == "blood pressure"     # reaches the reminder/hero


# ── snooze ───────────────────────────────────────────────────────────────────
def _uid(mid):
    return execute("SELECT user_id FROM medicines WHERE id=?", (mid,), fetchone=True)["user_id"]


def test_snooze_becomes_due_then_taken_clears_it(client):
    m = _add_med(client)
    uid = _uid(m["id"])
    r = client.post(f"/api/medicines/{m['id']}/snooze", json={"time": "09:00", "minutes": 15})
    assert r.status_code == 200 and r.get_json()["success"]

    from db.medicines import get_due_snoozes
    with user_context(uid):
        assert get_due_snoozes() == []            # 15 min out — not due yet
    # fast-forward the snooze into the past
    execute("UPDATE dose_snoozes SET snooze_until=? WHERE med_id=? AND user_id=?",
            ("2000-01-01T00:00:00", m["id"], uid), commit=True)
    with user_context(uid):
        due = get_due_snoozes()
        assert any(s["med_id"] == m["id"] for s in due)

    # Taking the dose clears the snooze so it never re-fires.
    today = dt.date.today().isoformat()
    client.post(f"/api/medicines/{m['id']}/log", json={"date": today, "time": "09:00", "taken": True})
    with user_context(uid):
        assert get_due_snoozes() == []


def test_snooze_route_rejects_unknown_medicine(client):
    r = client.post("/api/medicines/deadbeef/snooze", json={"time": "09:00"})
    assert r.status_code == 404


def test_scheduler_repushes_a_due_snooze(client, monkeypatch):
    import scheduler, push
    m = _add_med(client)
    uid = _uid(m["id"])
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id,endpoint,user_id,sub_json,created_at) VALUES (?,?,?,?,?)",
            ("s-snz", "https://push.test/snz", uid, "{}", "2026-01-01"), commit=True)
    client.post(f"/api/medicines/{m['id']}/snooze", json={"time": "09:00"})
    execute("UPDATE dose_snoozes SET snooze_until=? WHERE med_id=? AND user_id=?",
            ("2000-01-01T00:00:00", m["id"], uid), commit=True)

    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user", lambda u, t, b, *a, **k: (sent.append(t) or 1))
    scheduler._push_reminders()
    assert any("Still due" in t for t in sent)
    # marked notified → a second run doesn't spam
    sent.clear()
    scheduler._push_reminders()
    assert not any("Still due" in t for t in sent)
