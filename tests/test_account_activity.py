"""Where you're signed in, and what changed about who can see this account.

Tokens were stateless, so the only lever was token_version — which signs out
every device at once. Losing a phone meant logging every other device out too,
which is enough friction that people put it off.

The tests below pin two things equally: that a single device can now be signed
out, and that the feature did not quietly become a tracking log while doing it.
"""
import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute
from db import account_activity as aa

PW = "acct-pw-123456"
NEW_PW = "acct-pw-654321"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email, ua="Mozilla/5.0 (Windows NT 10.0) Chrome/120"):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW},
           headers={"User-Agent": ua})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]
    return c, uid


def _second_device(app, email, ua):
    c = app.test_client()
    c.post("/auth/login", json={"email": email, "password": PW},
           headers={"User-Agent": ua})
    return c


# ── It must not become a tracking log ───────────────────────────────────────

def test_no_ip_address_or_raw_user_agent_is_stored(app):
    """A security feature that quietly grows a location history has taken more
    than it gave."""
    cols = {r["name"] for r in execute("PRAGMA table_info(user_sessions)", fetchall=True)}
    for forbidden in ("ip", "ip_address", "remote_addr", "user_agent"):
        assert forbidden not in cols, f"user_sessions stores {forbidden}"

    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605 Safari/604.1"
    _register(app, "acct1@medeasy.test", ua=ua)
    stored = execute("SELECT device FROM user_sessions", fetchall=True)
    for row in stored:
        assert row["device"] not in (None, ""), "a device needs a readable name"
        assert "Mozilla" not in row["device"], "the raw user agent must not be kept"
        assert "AppleWebKit" not in row["device"]


def test_device_names_are_recognisable_but_coarse():
    assert aa.describe_device("Mozilla/5.0 (iPhone) Safari/604") == "Safari on iPhone"
    assert aa.describe_device("Mozilla/5.0 (Windows NT 10.0) Chrome/120") == "Chrome on Windows"
    assert aa.describe_device("Mozilla/5.0 (X11; Linux) Firefox/121") == "Firefox on Linux"
    assert aa.describe_device("") == "Unknown device"


# ── Sessions ────────────────────────────────────────────────────────────────

def test_signing_in_lists_the_device(app):
    c, uid = _register(app, "acct2@medeasy.test")
    sessions = c.get("/api/account/sessions").get_json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["device"] == "Chrome on Windows"
    assert sessions[0]["current"] is True, "you should be able to tell which one you're on"


def test_a_second_device_appears_separately(app):
    c, uid = _register(app, "acct3@medeasy.test")
    _second_device(app, "acct3@medeasy.test", "Mozilla/5.0 (iPhone) Safari/604")
    devices = {s["device"] for s in c.get("/api/account/sessions").get_json()["sessions"]}
    assert devices == {"Chrome on Windows", "Safari on iPhone"}


def test_signing_out_one_device_leaves_the_others_alone(app):
    """The whole point. Before this, losing a phone meant signing every device
    out, which is enough friction that people put it off."""
    c, uid = _register(app, "acct4@medeasy.test")
    phone = _second_device(app, "acct4@medeasy.test", "Mozilla/5.0 (iPhone) Safari/604")
    assert phone.get("/api/account/sessions").status_code == 200

    target = next(s for s in c.get("/api/account/sessions").get_json()["sessions"]
                  if s["device"] == "Safari on iPhone")
    assert c.delete(f"/api/account/sessions/{target['id']}").get_json()["success"] is True

    assert phone.get("/api/account/sessions").status_code == 401, "the phone must be out"
    assert c.get("/api/account/sessions").status_code == 200, "and this one must not"


def test_a_revoked_session_stays_out(app):
    c, uid = _register(app, "acct5@medeasy.test")
    phone = _second_device(app, "acct5@medeasy.test", "Mozilla/5.0 (Android) Chrome/120")
    target = next(s for s in c.get("/api/account/sessions").get_json()["sessions"]
                  if s["device"] == "Chrome on Android")
    c.delete(f"/api/account/sessions/{target['id']}")
    for _ in range(3):
        assert phone.get("/api/account/sessions").status_code == 401


def test_revoke_all_keeps_the_device_you_are_on(app):
    """Signing everything out including yourself is what "change password"
    already did. This is the version you can actually use."""
    c, uid = _register(app, "acct6@medeasy.test")
    _second_device(app, "acct6@medeasy.test", "Mozilla/5.0 (iPhone) Safari/604")
    _second_device(app, "acct6@medeasy.test", "Mozilla/5.0 (Macintosh) Firefox/121")
    r = c.post("/api/account/sessions/revoke-all").get_json()
    assert r["signed_out"] == 2
    left = c.get("/api/account/sessions").get_json()["sessions"]
    assert len(left) == 1 and left[0]["current"] is True


def test_one_user_cannot_see_or_end_anothers_session(app):
    ca, _ = _register(app, "acct7a@medeasy.test")
    cb, _ = _register(app, "acct7b@medeasy.test")
    mine = ca.get("/api/account/sessions").get_json()["sessions"][0]["id"]
    assert cb.get("/api/account/sessions").get_json()["sessions"][0]["id"] != mine
    assert cb.delete(f"/api/account/sessions/{mine}").get_json()["success"] is False
    assert ca.get("/api/account/sessions").status_code == 200, "someone else ended my session"


def test_a_token_without_a_session_id_still_works(app):
    """Tokens minted before this feature carry no session id. Expiring everyone's
    login to ship a list of devices would be a poor trade."""
    with app.test_request_context():
        from auth import make_token, read_token
        c, uid = _register(app, "acct8@medeasy.test")
        legacy = make_token(uid)              # no session id
        assert read_token(legacy) == uid


# ── The log ─────────────────────────────────────────────────────────────────

def test_signing_in_is_recorded(app):
    c, uid = _register(app, "acct9@medeasy.test")
    kinds = [e["kind"] for e in c.get("/api/account/activity").get_json()["events"]]
    assert "signed_in" in kinds


def test_a_password_change_is_recorded_and_ends_other_devices(app):
    c, uid = _register(app, "acct10@medeasy.test")
    phone = _second_device(app, "acct10@medeasy.test", "Mozilla/5.0 (iPhone) Safari/604")
    r = c.post("/auth/change-password", json={"current_password": PW, "new_password": NEW_PW})
    assert r.status_code == 200, r.get_json()
    assert phone.get("/api/account/sessions").status_code == 401
    kinds = [e["kind"] for e in c.get("/api/account/activity").get_json()["events"]]
    assert "password_changed" in kinds


def test_events_carry_a_plain_english_label(app):
    """The page shows the label, not the raw kind — "signed_out_device" is not
    something to put in front of someone."""
    c, uid = _register(app, "acct11@medeasy.test")
    for e in c.get("/api/account/activity").get_json()["events"]:
        assert e["label"] and e["label"] != e["kind"]
        assert "_" not in e["label"]


def test_an_unknown_event_kind_is_refused(app):
    """A fixed vocabulary is what lets the page describe every row in words."""
    c, uid = _register(app, "acct12@medeasy.test")
    with user_context(uid):
        before = len(aa.list_events())
        aa.log_event("something_made_up", "detail")
        assert len(aa.list_events()) == before


def test_the_log_has_no_delete(app):
    """A security log the account holder can edit is not a security log."""
    assert not hasattr(aa, "delete_event")
    assert not hasattr(aa, "clear_events")
    from db.trash import NOT_TRASHABLE
    assert "security_events" in NOT_TRASHABLE


def test_logging_never_breaks_the_action_it_records(app):
    """A password change that fails because its audit line could not be written
    is worse than an incomplete log."""
    c, uid = _register(app, "acct13@medeasy.test")
    with user_context(uid):
        execute("DROP TABLE security_events", commit=True)
        aa.log_event("signed_in", "x")          # must not raise
        init_db()


def test_activity_is_scoped_per_user(app):
    ca, _ = _register(app, "acct14a@medeasy.test")
    cb, _ = _register(app, "acct14b@medeasy.test")
    a_events = ca.get("/api/account/activity").get_json()["events"]
    b_events = cb.get("/api/account/activity").get_json()["events"]
    assert len(a_events) >= 1 and len(b_events) >= 1
    assert {e["id"] for e in a_events}.isdisjoint({e["id"] for e in b_events})


# ── Share receipts ──────────────────────────────────────────────────────────

def test_share_receipts_report_openings_not_people(app):
    c, uid = _register(app, "acct15@medeasy.test")
    made = c.post("/api/share/snapshot", json={"scope": "summary"})
    assert made.status_code in (200, 201), made.get_json()
    shares = c.get("/api/account/shares").get_json()["shares"]
    assert len(shares) == 1
    assert shares[0]["views"] == 0
    assert shares[0]["scope"] == "summary"
    assert "token" not in shares[0], "a receipt must not re-expose the link's token"


def test_share_receipts_are_scoped_per_user(app):
    ca, _ = _register(app, "acct16a@medeasy.test")
    cb, _ = _register(app, "acct16b@medeasy.test")
    ca.post("/api/share/snapshot", json={"scope": "summary"})
    assert cb.get("/api/account/shares").get_json()["shares"] == []


# ── Walls ───────────────────────────────────────────────────────────────────

def test_account_endpoints_are_walled_from_a_caregiver():
    """A caregiver managing health data has no business seeing someone's
    devices, and less business ending a session."""
    from auth import _is_private_while_acting
    for path in ("/api/account/sessions", "/api/account/activity",
                 "/api/account/shares"):
        assert _is_private_while_acting(path), path
        assert _is_private_while_acting(path.replace("/api/", "/api/v1/")), path


def test_routes_require_auth(app):
    anon = app.test_client()
    assert anon.get("/api/account/sessions").status_code == 401
    assert anon.get("/api/account/activity").status_code == 401
    assert anon.get("/api/account/shares").status_code == 401
    assert anon.post("/api/account/sessions/revoke-all").status_code == 401
