"""Measurement reminders: CRUD + validation, and the scheduler firing them."""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, execute, user_context

PW = "meas-pw-12345"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.post("/auth/register", json={"email": "measrem1@medeasy.test", "password": PW})
    return c


def test_add_list_toggle_delete(client):
    r = client.post("/api/measurement-reminders", json={"kind": "blood_pressure", "time": "08:00"})
    assert r.status_code == 200 and r.get_json()["success"]
    rid = r.get_json()["reminder"]["id"]
    assert any(x["id"] == rid for x in client.get("/api/measurement-reminders").get_json()["reminders"])

    # toggle off
    client.post(f"/api/measurement-reminders/{rid}/toggle")
    row = next(x for x in client.get("/api/measurement-reminders").get_json()["reminders"] if x["id"] == rid)
    assert row["enabled"] == 0

    assert client.delete(f"/api/measurement-reminders/{rid}").status_code == 200
    assert not any(x["id"] == rid for x in client.get("/api/measurement-reminders").get_json()["reminders"])


def test_validation(client):
    assert client.post("/api/measurement-reminders", json={"kind": "wizardry", "time": "08:00"}).status_code == 400
    assert client.post("/api/measurement-reminders", json={"kind": "weight", "time": "nope"}).status_code == 400


def test_scheduler_fires_at_the_set_time(app, monkeypatch):
    import scheduler, push
    c = app.test_client()
    c.post("/auth/register", json={"email": "measrem2@medeasy.test", "password": PW})
    # a reminder timed to "now" so it lands in the 0–15 min window
    hhmm = dt.datetime.now().strftime("%H:%M")
    rid = c.post("/api/measurement-reminders",
                 json={"kind": "blood_sugar", "time": hhmm}).get_json()["reminder"]["id"]
    uid = execute("SELECT user_id FROM measurement_reminders WHERE id=?", (rid,), fetchone=True)["user_id"]
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id,endpoint,user_id,sub_json,created_at) VALUES (?,?,?,?,?)",
            ("s-meas", "https://push.test/meas", uid, "{}", "2026-01-01"), commit=True)
    execute("DELETE FROM notification_log WHERE user_id=?", (uid,), commit=True)

    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user", lambda u, t, b, *a, **k: (sent.append(t) or 1))
    scheduler._push_reminders()
    assert any("blood sugar" in t.lower() for t in sent), "measurement reminder did not fire"

    # deduped: a second run in the same window/day doesn't re-notify
    sent.clear()
    scheduler._push_reminders()
    assert not any("blood sugar" in t.lower() for t in sent)


def test_disabled_reminder_does_not_fire(app, monkeypatch):
    import scheduler, push
    c = app.test_client()
    c.post("/auth/register", json={"email": "measrem3@medeasy.test", "password": PW})
    hhmm = dt.datetime.now().strftime("%H:%M")
    rid = c.post("/api/measurement-reminders",
                 json={"kind": "weight", "time": hhmm}).get_json()["reminder"]["id"]
    c.post(f"/api/measurement-reminders/{rid}/toggle")     # turn it off
    uid = execute("SELECT user_id FROM measurement_reminders WHERE id=?", (rid,), fetchone=True)["user_id"]
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id,endpoint,user_id,sub_json,created_at) VALUES (?,?,?,?,?)",
            ("s-meas3", "https://push.test/meas3", uid, "{}", "2026-01-01"), commit=True)
    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user", lambda u, t, b, *a, **k: (sent.append(t) or 1))
    scheduler._push_reminders()
    assert not any("weigh" in t.lower() for t in sent)
