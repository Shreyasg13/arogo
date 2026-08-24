"""Reminders stop silently — so the app has to say so, and only when it's true.

Every link in the chain that delivers a dose reminder (push configured, the
scheduler alive, a subscribed device) fails without any visible sign. Someone who
has handed their medication schedule to this app has deliberately stopped holding
it in their head; finding out by missing a dose is the failure the app exists to
prevent.

The opposite failure matters just as much. A warning shown to a person who isn't
waiting on any reminder is noise, and noise is how a real warning gets ignored
later — so these tests pin the silence as firmly as the alarm.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, new_id, now_iso
from db.reminder_health import reminder_health, STALE_AFTER_S

PW = "rh-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture(autouse=True)
def _push_available(monkeypatch):
    """Default to a correctly configured server, so each test isolates the one
    link it is about."""
    import push
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    yield


def _uid(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    return c, dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]


def _heartbeat(seconds_ago):
    execute("DELETE FROM app_config WHERE key='scheduler_last_run'", commit=True)
    if seconds_ago is None:
        return                                     # never ran
    stamp = (dt.datetime.now() - dt.timedelta(seconds=seconds_ago)).isoformat()
    execute("INSERT INTO app_config (key, value) VALUES ('scheduler_last_run', ?)",
            (stamp,), commit=True)


def _subscribe(uid):
    execute("""INSERT INTO push_subscriptions (id, endpoint, sub_json, created_at, user_id)
               VALUES (?,?,?,?,?)""",
            (new_id(), f"https://push.test/{new_id()}", "{}", now_iso(), uid), commit=True)


def _add_med(client, name="Metformin"):
    client.post("/api/medicines", json={"name": name, "frequency": "once_daily",
                                        "times": ["09:00"]})


def _codes(h):
    return {p["code"] for p in h["problems"]}


# ── Silence when there is nothing to warn about ─────────────────────────────

def test_a_user_waiting_on_nothing_is_never_warned(app):
    """No scheduled medicine, no subscribed device — a dead scheduler doesn't
    affect them, so saying anything is just noise."""
    _, uid = _uid(app, "rh1@medeasy.test")
    _heartbeat(3 * 3600)                            # thoroughly stalled
    with user_context(uid):
        h = reminder_health(uid)
    assert h["relying"] is False
    assert h["ok"] is True
    assert h["problems"] == []


def test_a_healthy_setup_says_nothing(app):
    _, uid = _uid(app, "rh2@medeasy.test")
    _subscribe(uid)
    _heartbeat(30)
    with user_context(uid):
        h = reminder_health(uid)
    assert h["relying"] is True
    assert h["ok"] is True, h["problems"]


def test_a_slow_tick_is_not_an_alarm(app):
    """Jobs run every five minutes. Warning at six would cry wolf constantly."""
    _, uid = _uid(app, "rh3@medeasy.test")
    _subscribe(uid)
    _heartbeat(STALE_AFTER_S - 60)
    with user_context(uid):
        assert reminder_health(uid)["ok"] is True


# ── Speaking up when it is true ─────────────────────────────────────────────

def test_a_stalled_scheduler_is_reported(app):
    c, uid = _uid(app, "rh4@medeasy.test")
    _add_med(c)
    _subscribe(uid)
    _heartbeat(STALE_AFTER_S + 120)
    with user_context(uid):
        h = reminder_health(uid)
    assert h["ok"] is False
    assert "scheduler_stalled" in _codes(h)
    assert h["scheduler"]["ok"] is False


def test_a_scheduled_medicine_alone_is_enough_to_be_relying(app):
    """Someone who added their medicines but never got as far as switching
    notifications on is exactly who this is for."""
    c, uid = _uid(app, "rh5@medeasy.test")
    _add_med(c)
    _heartbeat(30)
    with user_context(uid):
        h = reminder_health(uid)
    assert h["relying"] is True
    assert "no_device" in _codes(h)


def test_never_having_run_is_distinguished_from_having_stopped(app):
    """On a fresh install the worker simply hasn't written a heartbeat yet.
    Calling that "reminders have stopped" would be false and alarming."""
    c, uid = _uid(app, "rh6@medeasy.test")
    _add_med(c)
    _subscribe(uid)
    _heartbeat(None)
    with user_context(uid):
        h = reminder_health(uid)
    assert h["scheduler"]["never_ran"] is True
    assert "scheduler_never_ran" in _codes(h)
    assert "scheduler_stalled" not in _codes(h)


def test_an_unconfigured_server_is_reported_instead_of_the_scheduler(app, monkeypatch):
    """With no VAPID keys nothing can be delivered at all, so leading with a
    scheduler complaint would point at the wrong thing."""
    import push
    monkeypatch.setattr(push, "PUSH_AVAILABLE", False)
    c, uid = _uid(app, "rh7@medeasy.test")
    _add_med(c)
    _subscribe(uid)
    _heartbeat(None)
    with user_context(uid):
        h = reminder_health(uid)
    assert _codes(h) == {"push_unconfigured"}


def test_an_as_needed_medicine_does_not_make_someone_relying(app):
    """Nothing is scheduled for an as-needed medicine, so there is no reminder
    to miss."""
    c, uid = _uid(app, "rh8@medeasy.test")
    c.post("/api/medicines", json={"name": "Paracetamol", "frequency": "as_needed"})
    _heartbeat(3 * 3600)
    with user_context(uid):
        h = reminder_health(uid)
    assert h["relying"] is False and h["ok"] is True


# ── What it must never say ─────────────────────────────────────────────────

def test_it_never_claims_a_dose_was_missed(app):
    """The app has no idea whether the medicine was taken — only whether it sent
    a reminder. Asserting a missed dose would invent a fact about the user."""
    c, uid = _uid(app, "rh9@medeasy.test")
    _add_med(c)
    _subscribe(uid)
    _heartbeat(6 * 3600)
    with user_context(uid):
        h = reminder_health(uid)
    text = " ".join(p["title"] + " " + p["detail"] for p in h["problems"]).lower()
    for phrase in ("missed", "you did not take", "you forgot", "overdue dose"):
        assert phrase not in text, f"must not claim {phrase!r}: {text}"


def test_it_does_not_pretend_the_user_can_fix_the_server(app):
    c, uid = _uid(app, "rh10@medeasy.test")
    _add_med(c)
    _subscribe(uid)
    _heartbeat(STALE_AFTER_S + 60)
    with user_context(uid):
        h = reminder_health(uid)
    stalled = next(p for p in h["problems"] if p["code"] == "scheduler_stalled")
    assert stalled["actionable_by_user"] is False


def test_the_user_fixable_case_is_marked_as_such(app):
    c, uid = _uid(app, "rh11@medeasy.test")
    _add_med(c)
    _heartbeat(30)
    with user_context(uid):
        h = reminder_health(uid)
    nod = next(p for p in h["problems"] if p["code"] == "no_device")
    assert nod["actionable_by_user"] is True


def test_the_staleness_threshold_matches_healthz(app):
    """A human reading the banner and an uptime check reading /healthz must not
    disagree about whether the scheduler is up."""
    import re
    src = open("app.py", encoding="utf-8").read()
    m = re.search(r"STALE_AFTER_S\s*=\s*(\d+)\s*\*\s*60", src)
    assert m, "couldn't find /healthz's threshold"
    assert int(m.group(1)) * 60 == STALE_AFTER_S


# ── Route ───────────────────────────────────────────────────────────────────

def test_route_requires_auth(app):
    assert app.test_client().get("/api/reminders/health").status_code == 401


def test_route_is_scoped_to_the_caller(app):
    ca, _ = _uid(app, "rh12a@medeasy.test")
    cb, ub = _uid(app, "rh12b@medeasy.test")
    _add_med(cb)
    _subscribe(ub)
    _heartbeat(30)
    assert ca.get("/api/reminders/health").get_json()["relying"] is False
    assert cb.get("/api/reminders/health").get_json()["relying"] is True
