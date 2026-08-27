"""The screen lock — and specifically, that it is a lock and not a curtain.

The whole feature turns on one property: a locked session must actually be
refused by the SERVER. A lock drawn over the interface is theatre, because the
session cookie is still valid and devtools, a second tab or curl walk straight
past it. So most of this file is one question asked in different ways: with the
device locked, can the data still be got out of it?

The second thread is the emergency card. It stays readable while locked by
default, because that card exists to be read by a stranger who is helping you —
a lock that hides it costs someone help rather than protecting them. That is a
real trade, so it is a setting, and the setting is tested in both directions.
"""
import datetime as dt

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, now_iso
from db import applock

PW = "lock-pw-123456"
PIN = "8317"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _user(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,),
                       fetchone=True))["id"]
    return c, uid


def _sid(uid):
    r = execute("""SELECT id FROM user_sessions WHERE user_id=? AND revoked_at IS NULL
                   ORDER BY created_at DESC LIMIT 1""", (uid,), fetchone=True)
    return r["id"] if r else None


def _enable(c, pin=PIN):
    return c.post("/api/lock/pin", json={"password": PW, "pin": pin})


def _lock(c):
    return c.post("/api/lock/now")


# ── A lock that actually locks ──────────────────────────────────────────────

def test_a_locked_device_refuses_health_data(app):
    """The one that matters. 423, not a screen."""
    c, uid = _user(app, "lock1@medeasy.test")
    assert _enable(c).status_code == 200
    assert _lock(c).get_json()["success"] is True
    for path in ("/api/medicines", "/api/vitals", "/api/reports", "/api/symptoms"):
        r = c.get(path)
        assert r.status_code == 423, f"{path} served data to a locked device"
        assert r.get_json()["code"] == "LOCKED"


def test_a_locked_device_refuses_writes_too(app):
    """Reading is the obvious risk; writing to someone's medication record from
    a device they left on the table is the worse one."""
    c, uid = _user(app, "lock2@medeasy.test")
    _enable(c); _lock(c)
    r = c.post("/api/symptoms", json={"name": "Planted", "severity": 5})
    assert r.status_code == 423


def test_locking_uses_423_not_401(app):
    """401 makes the client sign the user out — the opposite of what locking a
    device you are about to put down means."""
    c, uid = _user(app, "lock3@medeasy.test")
    _enable(c); _lock(c)
    assert c.get("/api/medicines").status_code == 423


def test_the_export_and_backup_paths_are_locked_too(app):
    """The bulk routes are exactly what someone holding the device would reach
    for, and they carry everything at once."""
    c, uid = _user(app, "lock4@medeasy.test")
    _enable(c); _lock(c)
    for path in ("/api/backup", "/api/account/export", "/api/export"):
        assert c.get(path).status_code == 423, path


def test_unlocking_with_the_pin_restores_access(app):
    c, uid = _user(app, "lock5@medeasy.test")
    _enable(c); _lock(c)
    assert c.get("/api/medicines").status_code == 423
    assert c.post("/api/lock/unlock", json={"pin": PIN}).status_code == 200
    assert c.get("/api/medicines").status_code == 200


def test_the_account_password_also_unlocks(app):
    """Forgetting a PIN must never be a way to lose your own medical history."""
    c, uid = _user(app, "lock6@medeasy.test")
    _enable(c); _lock(c)
    assert c.post("/api/lock/unlock", json={"password": PW}).status_code == 200
    assert c.get("/api/medicines").status_code == 200


def test_a_wrong_pin_does_not_unlock(app):
    c, uid = _user(app, "lock7@medeasy.test")
    _enable(c); _lock(c)
    r = c.post("/api/lock/unlock", json={"pin": "0000"})
    assert r.status_code == 401
    assert c.get("/api/medicines").status_code == 423


def test_repeated_wrong_pins_lock_the_pin_out(app):
    """A four-digit PIN is ten thousand guesses. The lockout is the only thing
    that makes it worth anything."""
    c, uid = _user(app, "lock8@medeasy.test")
    _enable(c); _lock(c)
    for i in range(applock.MAX_PIN_FAILURES):
        c.post("/api/lock/unlock", json={"pin": "0000"})
    r = c.post("/api/lock/unlock", json={"pin": PIN}).get_json()
    assert r["success"] is False and r.get("locked_out") is True
    # The password still works — the lockout stops guessing, it does not strand
    # the account's owner.
    assert c.post("/api/lock/unlock", json={"password": PW}).status_code == 200


def test_unlocking_clears_the_failure_count(app):
    c, uid = _user(app, "lock9@medeasy.test")
    _enable(c); _lock(c)
    c.post("/api/lock/unlock", json={"pin": "0000"})
    c.post("/api/lock/unlock", json={"pin": PIN})
    with user_context(uid):
        assert applock._row(uid)["failures"] == 0


# ── The PIN itself ──────────────────────────────────────────────────────────

def test_a_pin_is_hashed_not_stored(app):
    c, uid = _user(app, "lock10@medeasy.test")
    _enable(c)
    stored = execute("SELECT pin_hash FROM user_lock WHERE user_id=?", (uid,),
                     fetchone=True)["pin_hash"]
    assert PIN not in stored, "the PIN is recoverable from the database"
    assert len(stored) > 20, "that does not look like a real password hash"


def test_an_obvious_pin_is_refused(app):
    c, uid = _user(app, "lock11@medeasy.test")
    with user_context(uid):
        assert applock.set_pin(uid, "1111")["ok"] is False
        assert applock.set_pin(uid, "1234")["ok"] is False
        assert applock.set_pin(uid, "0000")["ok"] is False
        assert applock.set_pin(uid, "8317")["ok"] is True


def test_a_pin_must_be_the_right_length(app):
    c, uid = _user(app, "lock12@medeasy.test")
    with user_context(uid):
        assert applock.set_pin(uid, "12")["ok"] is False
        assert applock.set_pin(uid, "1" * 20)["ok"] is False


def test_setting_a_pin_needs_the_account_password(app):
    """Otherwise someone holding an unlocked device sets their own PIN and locks
    the owner out of their own records."""
    c, uid = _user(app, "lock13@medeasy.test")
    r = c.post("/api/lock/pin", json={"password": "wrong", "pin": PIN})
    assert r.status_code == 401
    with user_context(uid):
        assert applock.is_enabled(uid) is False


def test_turning_the_lock_off_needs_the_password_too(app):
    c, uid = _user(app, "lock14@medeasy.test")
    _enable(c)
    assert c.delete("/api/lock/pin", json={"password": "wrong"}).status_code == 401
    with user_context(uid):
        assert applock.is_enabled(uid) is True
    assert c.delete("/api/lock/pin", json={"password": PW}).status_code == 200
    with user_context(uid):
        assert applock.is_enabled(uid) is False


def test_locking_is_refused_when_there_is_no_pin(app):
    """A lock with no way back in is a way to lose access to your own records."""
    c, uid = _user(app, "lock15@medeasy.test")
    r = c.post("/api/lock/now")
    assert r.status_code == 400
    assert c.get("/api/medicines").status_code == 200


# ── The emergency card ──────────────────────────────────────────────────────

def test_the_emergency_card_stays_readable_while_locked(app):
    """It exists to be read by a stranger who is helping you. A lock that hides
    it costs someone help."""
    c, uid = _user(app, "lock16@medeasy.test")
    _enable(c); _lock(c)
    assert c.get("/api/health-id").status_code == 200
    # ...while everything else is still shut.
    assert c.get("/api/medicines").status_code == 423


def test_the_emergency_card_can_be_hidden_when_locked(app):
    """A real trade, so it is the user's call — not everyone wants their
    conditions readable by whoever picks up the tablet."""
    c, uid = _user(app, "lock17@medeasy.test")
    _enable(c)
    c.post("/api/lock/settings", json={"emergency_while_locked": 0})
    _lock(c)
    assert c.get("/api/health-id").status_code == 423


def test_the_default_is_reachable(app):
    """Defaulting the other way would mean the common case is the one that
    costs someone help."""
    c, uid = _user(app, "lock18@medeasy.test")
    _enable(c)
    assert c.get("/api/lock").get_json()["emergency_while_locked"] is True


# ── Idle ────────────────────────────────────────────────────────────────────

def test_an_idle_session_locks_itself(app):
    """Enforced from the server's own record of last use, not from a timer in
    the page — a tab that was closed never runs its countdown."""
    c, uid = _user(app, "lock19@medeasy.test")
    _enable(c)
    c.post("/api/lock/settings", json={"idle_minutes": 5})
    old = (dt.datetime.now() - dt.timedelta(minutes=30)).isoformat()
    execute("UPDATE user_sessions SET last_seen=? WHERE user_id=?", (old, uid),
            commit=True)
    assert c.get("/api/medicines").status_code == 423


def test_a_session_in_use_does_not_lock(app):
    c, uid = _user(app, "lock20@medeasy.test")
    _enable(c)
    c.post("/api/lock/settings", json={"idle_minutes": 30})
    recent = (dt.datetime.now() - dt.timedelta(minutes=2)).isoformat()
    execute("UPDATE user_sessions SET last_seen=? WHERE user_id=?", (recent, uid),
            commit=True)
    assert c.get("/api/medicines").status_code == 200


def test_idle_zero_means_never(app):
    c, uid = _user(app, "lock21@medeasy.test")
    _enable(c)
    c.post("/api/lock/settings", json={"idle_minutes": 0})
    old = (dt.datetime.now() - dt.timedelta(days=3)).isoformat()
    execute("UPDATE user_sessions SET last_seen=? WHERE user_id=?", (old, uid),
            commit=True)
    assert c.get("/api/medicines").status_code == 200


def test_the_idle_clock_is_read_before_the_request_touches_it(app):
    """The bug this pins: touch_session sets last_seen to now on every request,
    including the one being judged. Reading it after the touch would mean the
    idle lock could never fire at all."""
    import inspect
    src = inspect.getsource(auth_module.read_token)
    assert src.index('prev_seen') < src.index('touch_session(sid, uid'), (
        'last_seen is read after it has already been updated')


def test_last_seen_is_kept_to_the_minute_when_the_lock_is_on(app):
    """The other half of that bug: last_seen is normally written at most once an
    hour to spare the SD card, which is uselessly coarse for a 15-minute idle
    timeout — it would lock someone out mid-use."""
    from db.account_activity import (TOUCH_INTERVAL_SECONDS,
                                     LOCKED_TOUCH_INTERVAL_SECONDS)
    assert LOCKED_TOUCH_INTERVAL_SECONDS <= 60
    assert TOUCH_INTERVAL_SECONDS > LOCKED_TOUCH_INTERVAL_SECONDS
    import inspect
    src = inspect.getsource(auth_module.read_token)
    assert 'LOCKED_TOUCH_INTERVAL_SECONDS' in src


def test_a_silly_idle_value_is_clamped(app):
    """An idle window of 9,999 minutes is a lock that never engages, which reads
    as protection and isn't."""
    c, uid = _user(app, "lock22@medeasy.test")
    _enable(c)
    r = c.post("/api/lock/settings", json={"idle_minutes": 99999}).get_json()
    assert r["settings"]["idle_minutes"] in applock.IDLE_CHOICES


def test_an_unreadable_last_seen_locks_rather_than_opens(app):
    """The safe direction: the cost of locking wrongly is typing a PIN; the cost
    of the other choice is an unlocked medical history."""
    c, uid = _user(app, "lock23@medeasy.test")
    _enable(c)
    c.post("/api/lock/settings", json={"idle_minutes": 15})
    execute("UPDATE user_sessions SET last_seen=? WHERE user_id=?",
            ("not-a-timestamp", uid), commit=True)
    with user_context(uid):
        assert applock.session_is_locked(_sid(uid), uid, "not-a-timestamp") is True


# ── Scope ───────────────────────────────────────────────────────────────────

def test_locking_one_device_leaves_the_others_alone(app):
    """Locking the tablet you just put down must not lock you out on your
    phone."""
    email = "lock24@medeasy.test"
    tablet = app.test_client()
    tablet.post("/auth/register", json={"email": email, "password": PW})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,),
                       fetchone=True))["id"]
    phone = app.test_client()
    phone.post("/auth/login", json={"email": email, "password": PW})

    tablet.post("/api/lock/pin", json={"password": PW, "pin": PIN})
    tablet.post("/api/lock/now")
    assert tablet.get("/api/medicines").status_code == 423
    assert phone.get("/api/medicines").status_code == 200, \
        "locking one device locked another"


def test_one_users_lock_does_not_affect_another(app):
    ca, ua = _user(app, "lock25a@medeasy.test")
    cb, ub = _user(app, "lock25b@medeasy.test")
    _enable(ca); _lock(ca)
    assert cb.get("/api/medicines").status_code == 200


def test_the_lock_endpoints_are_reachable_while_locked(app):
    """Otherwise there is no way back in from the lock screen."""
    c, uid = _user(app, "lock26@medeasy.test")
    _enable(c); _lock(c)
    assert c.get("/api/lock").status_code == 200
    assert c.get("/api/lock").get_json()["locked"] is True


def test_signing_out_works_while_locked(app):
    """A borrowed device must always be handable back safe."""
    c, uid = _user(app, "lock27@medeasy.test")
    _enable(c); _lock(c)
    assert c.post("/auth/logout").status_code in (200, 204)


def test_the_allow_list_is_narrow(app):
    """Every path reachable while locked has to survive "would I be happy for a
    stranger holding this tablet to use it?"."""
    for p in ("/api/medicines", "/api/vitals", "/api/search?q=x", "/api/export",
              "/api/backup", "/api/thoughts", "/api/account/export"):
        assert not applock.path_allowed_while_locked(p, "anyone"), p


# ── Turned off ──────────────────────────────────────────────────────────────

def test_nothing_changes_for_someone_who_never_sets_a_pin(app):
    c, uid = _user(app, "lock28@medeasy.test")
    old = (dt.datetime.now() - dt.timedelta(days=5)).isoformat()
    execute("UPDATE user_sessions SET last_seen=? WHERE user_id=?", (old, uid),
            commit=True)
    assert c.get("/api/medicines").status_code == 200
    assert c.get("/api/lock").get_json()["configured"] is False


def test_the_lock_fails_open_rather_than_stranding_anyone(app):
    """A fault in the lock must never be a way to lose access to your own
    medicines."""
    import inspect
    src = inspect.getsource(auth_module.require_auth)
    lock_part = src[src.index('applock'):]
    assert 'except Exception' in lock_part[:900], (
        'a failure in the lock check would take the whole app down')


def test_enabling_and_disabling_are_written_to_the_activity_log(app):
    c, uid = _user(app, "lock29@medeasy.test")
    _enable(c)
    c.delete("/api/lock/pin", json={"password": PW})
    kinds = [e["kind"] for e in c.get("/api/account/activity").get_json()["events"]]
    assert "device_lock_enabled" in kinds
    assert "device_lock_disabled" in kinds
