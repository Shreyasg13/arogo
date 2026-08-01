"""Appointments: CRUD + validation, the upcoming filter, and reminder gating."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute

PW = "appt-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "appt@medeasy.test", "password": PW})
    return c


def _tomorrow():
    return (dt.date.today() + dt.timedelta(days=1)).isoformat()


def test_create_list_and_next(client):
    r = client.post("/api/appointments", json={
        "title": "Dr. Rao — cardiology", "kind": "doctor",
        "date": _tomorrow(), "time": "10:30", "location": "City Clinic"})
    assert r.status_code == 200 and r.get_json()["success"]
    aid = r.get_json()["appointment"]["id"]

    d = client.get("/api/appointments").get_json()
    assert any(a["id"] == aid for a in d["appointments"])
    assert d["next"] and d["next"]["title"] == "Dr. Rao — cardiology"
    # kind normalized, remind defaulted on
    appt = next(a for a in d["appointments"] if a["id"] == aid)
    assert appt["kind"] == "doctor" and appt["remind"] == 1


def test_validation(client):
    assert client.post("/api/appointments", json={"date": _tomorrow()}).status_code == 400  # no title
    assert client.post("/api/appointments", json={"title": "x", "date": "not-a-date"}).status_code == 400
    # an unknown kind is coerced to 'other', not rejected
    a = client.post("/api/appointments", json={"title": "x", "date": _tomorrow(), "kind": "wizardry"}).get_json()
    assert a["appointment"]["kind"] == "other"


def test_upcoming_filter_excludes_past(client):
    past = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    client.post("/api/appointments", json={"title": "old checkup", "date": past})
    up = client.get("/api/appointments?upcoming=1").get_json()["appointments"]
    assert all(a["date"] >= dt.date.today().isoformat() for a in up)
    assert not any(a["title"] == "old checkup" for a in up)


def test_delete(client):
    aid = client.post("/api/appointments",
                      json={"title": "temp", "date": _tomorrow()}).get_json()["appointment"]["id"]
    assert client.delete(f"/api/appointments/{aid}").status_code == 200
    assert not any(a["id"] == aid for a in client.get("/api/appointments").get_json()["appointments"])


def test_reminder_fires_then_dedups_and_respects_optout(app, monkeypatch):
    import scheduler, push
    c = app.test_client()
    c.post("/auth/register", json={"email": "appt2@medeasy.test", "password": PW})
    # one reminding appointment tomorrow, one with reminders off
    on = c.post("/api/appointments", json={"title": "Blood test", "kind": "lab",
                "date": _tomorrow(), "remind": True}).get_json()["appointment"]
    c.post("/api/appointments", json={"title": "Silent visit", "date": _tomorrow(), "remind": False})
    uid = execute("SELECT user_id FROM appointments WHERE id=?", (on["id"],), fetchone=True)["user_id"]
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id,endpoint,user_id,sub_json,created_at) VALUES (?,?,?,?,?)",
            ("s-appt", "https://push.test/appt", uid, "{}", "2026-01-01"), commit=True)
    execute("DELETE FROM notification_log WHERE user_id=?", (uid,), commit=True)

    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user", lambda u, t, b, *a, **k: (sent.append(t) or 1))

    scheduler._appointment_reminders()
    assert any("Blood test" in t for t in sent), "reminding appointment did not fire"
    assert not any("Silent visit" in t for t in sent), "opted-out appointment was pushed"

    # Second run the same day must not re-push (deduped per phase).
    sent.clear()
    scheduler._appointment_reminders()
    assert sent == []
