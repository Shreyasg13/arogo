"""Two-factor sign-in, verified backups, and medicine reconciliation.

The TOTP tests check the algorithm against the vectors published in RFC 6238
rather than against itself — a crypto implementation that only agrees with its
own output is worth nothing, and this one decides whether someone can reach
their own medicines.

The backup tests care less about taking a backup than about proving one is
readable. A file in a backups directory is not a backup; the failure mode worth
catching is a copy that looks healthy from the outside and won't open.
"""
import base64
import hashlib
import hmac
import os
import struct
import time

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db, user_context, execute, now_iso, new_id
from db import totp

PW = "sec-pw-123456"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _register(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": PW})
    uid = dict(execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True))["id"]
    return c, uid


def _enable_2fa(client):
    setup = client.post("/api/2fa/setup").get_json()
    secret = setup["secret"]
    code = totp.code_at(secret, totp.current_step())
    res = client.post("/api/2fa/confirm", json={"code": code}).get_json()
    assert res["success"] is True, res
    return secret, res["recovery_codes"]


# ── The algorithm, against the published vectors ────────────────────────────

def test_totp_matches_rfc6238_test_vectors():
    """RFC 6238 Appendix B, SHA-1, secret "12345678901234567890". The published
    values are 8-digit; a 6-digit code is the same truncation mod 10^6, so it is
    the last six digits."""
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    for unix_time, expected8 in [(59, "94287082"), (1111111109, "07081804"),
                                 (1111111111, "14050471"), (1234567890, "89005924"),
                                 (2000000000, "69279037"), (20000000000, "65353130")]:
        step = unix_time // 30
        assert totp.code_at(secret, step) == expected8[-6:], f"t={unix_time}"


def test_hotp_matches_rfc4226_test_vectors():
    """RFC 4226 Appendix D — the counter-based scheme TOTP is built on."""
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    expected = ["755224", "287082", "359152", "969429", "338314",
                "254676", "287922", "162583", "399871", "520489"]
    for counter, want in enumerate(expected):
        assert totp.code_at(secret, counter) == want, f"counter={counter}"


def test_secrets_are_long_and_never_repeat():
    seen = {totp.generate_secret() for _ in range(50)}
    assert len(seen) == 50
    for s in seen:
        assert len(base64.b32decode(s + "=" * (-len(s) % 8))) == 20   # 160 bits


def test_provisioning_uri_is_scannable():
    uri = totp.provisioning_uri("ABCDEFGH", "someone@example.test")
    assert uri.startswith("otpauth://totp/")
    assert "secret=ABCDEFGH" in uri and "issuer=Arogo" in uri


# ── Enrolment must be proved, never assumed ─────────────────────────────────

def test_an_unconfirmed_secret_never_gates_sign_in(app):
    """Turning 2FA on and only then discovering the phone's clock is wrong is
    how people lock themselves out of their own records."""
    c, uid = _register(app, "sec1@medeasy.test")
    c.post("/api/2fa/setup")
    assert totp.is_enabled(uid) is False
    r = app.test_client().post("/auth/login",
                               json={"email": "sec1@medeasy.test", "password": PW})
    assert r.get_json().get("needs_2fa") is not True, "an unconfirmed setup blocked login"


def test_a_wrong_code_does_not_enable_it(app):
    c, uid = _register(app, "sec2@medeasy.test")
    c.post("/api/2fa/setup")
    r = c.post("/api/2fa/confirm", json={"code": "000000"}).get_json()
    assert r["success"] is False
    assert totp.is_enabled(uid) is False


def test_confirming_enables_it_and_returns_recovery_codes_once(app):
    c, uid = _register(app, "sec3@medeasy.test")
    _, codes = _enable_2fa(c)
    assert totp.is_enabled(uid) is True
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    # Nothing keeps a readable copy — the stored form must not contain them.
    stored = execute("SELECT recovery FROM user_totp WHERE user_id=?", (uid,),
                     fetchone=True)["recovery"]
    for code in codes:
        assert code not in stored, "a recovery code is stored in the clear"


# ── Sign-in ─────────────────────────────────────────────────────────────────

def test_login_stops_at_the_second_factor(app):
    c, uid = _register(app, "sec4@medeasy.test")
    secret, _ = _enable_2fa(c)

    fresh = app.test_client()
    r = fresh.post("/auth/login", json={"email": "sec4@medeasy.test", "password": PW})
    body = r.get_json()
    assert body["needs_2fa"] is True and body["challenge"]
    # No session was handed out at the password step.
    assert fresh.get("/api/2fa").status_code == 401

    # The NEXT window's code, not this one's: confirming enrolment already
    # burned the current step, and re-offering it is correctly refused as a
    # replay. In real use the user simply waits for the code to roll over.
    done = fresh.post("/auth/login/2fa",
                      json={"challenge": body["challenge"],
                            "code": totp.code_at(secret, totp.current_step() + 1)})
    assert done.status_code == 200 and done.get_json()["success"] is True
    assert fresh.get("/api/2fa").status_code == 200


def test_the_challenge_cannot_be_used_as_a_session(app):
    """It is signed with its own salt, so presenting it as a cookie must fail —
    otherwise the password step alone would be enough."""
    c, uid = _register(app, "sec5@medeasy.test")
    _enable_2fa(c)
    fresh = app.test_client()
    challenge = fresh.post("/auth/login",
                           json={"email": "sec5@medeasy.test",
                                 "password": PW}).get_json()["challenge"]
    fresh.set_cookie("me_session", challenge)
    assert fresh.get("/api/2fa").status_code == 401


def test_a_wrong_code_does_not_sign_you_in(app):
    c, uid = _register(app, "sec6@medeasy.test")
    _enable_2fa(c)
    fresh = app.test_client()
    ch = fresh.post("/auth/login", json={"email": "sec6@medeasy.test",
                                         "password": PW}).get_json()["challenge"]
    r = fresh.post("/auth/login/2fa", json={"challenge": ch, "code": "000000"})
    assert r.status_code == 401
    assert fresh.get("/api/2fa").status_code == 401


def test_a_code_cannot_be_replayed(app):
    """A code read over a shoulder must not stay usable inside its own window."""
    c, uid = _register(app, "sec7@medeasy.test")
    secret, _ = _enable_2fa(c)
    code = totp.code_at(secret, totp.current_step())
    # The confirm step already burned the current step, so a fresh one is needed.
    with user_context(uid):
        execute("UPDATE user_totp SET last_used_step=NULL WHERE user_id=?", (uid,),
                commit=True)
        assert totp.verify(uid, code) is True
        assert totp.verify(uid, code) is False, "the same code was accepted twice"


def test_a_recovery_code_works_once(app):
    c, uid = _register(app, "sec8@medeasy.test")
    _, codes = _enable_2fa(c)
    with user_context(uid):
        assert totp.recovery_codes_left(uid) == totp.RECOVERY_CODE_COUNT
        assert totp.verify(uid, codes[0]) is True
        assert totp.recovery_codes_left(uid) == totp.RECOVERY_CODE_COUNT - 1
        assert totp.verify(uid, codes[0]) is False, "a recovery code was reusable"


def test_recovery_codes_are_forgiving_about_formatting(app):
    """Someone reading one off paper should not fail on a dash or capital."""
    c, uid = _register(app, "sec9@medeasy.test")
    _, codes = _enable_2fa(c)
    messy = codes[0].replace("-", " ").upper()
    with user_context(uid):
        assert totp.verify(uid, messy) is True


# ── Turning it off ──────────────────────────────────────────────────────────

def test_disabling_requires_the_password(app):
    """A borrowed unlocked phone must not be enough to strip a security control."""
    c, uid = _register(app, "sec10@medeasy.test")
    _enable_2fa(c)
    bad = c.post("/api/2fa/disable", json={"password": "not-the-password"})
    assert bad.status_code == 401
    assert totp.is_enabled(uid) is True
    good = c.post("/api/2fa/disable", json={"password": PW})
    assert good.status_code == 200
    assert totp.is_enabled(uid) is False


def test_2fa_changes_are_recorded_in_the_security_log(app):
    c, uid = _register(app, "sec11@medeasy.test")
    _enable_2fa(c)
    c.post("/api/2fa/disable", json={"password": PW})
    kinds = [e["kind"] for e in c.get("/api/account/activity").get_json()["events"]]
    assert "two_factor_enabled" in kinds and "two_factor_disabled" in kinds


def test_2fa_is_walled_from_a_caregiver():
    from auth import _is_private_while_acting
    assert _is_private_while_acting("/api/2fa")
    assert _is_private_while_acting("/api/v1/2fa")


def test_the_secret_is_never_searchable():
    from db.search import NOT_SEARCHABLE
    assert "user_totp" in NOT_SEARCHABLE


# ── Backups ─────────────────────────────────────────────────────────────────

def test_a_backup_is_verified_not_just_written(tmp_path, monkeypatch):
    """A file existing in a backups directory is not a backup.

    Pointed at a real file rather than skipped when the suite runs on the
    in-memory mapping — a skipped test reads as a pass in the summary line, and
    that is exactly how the QR bug survived several releases.
    """
    import sqlite3
    from db import backups
    import db.core as core

    real = tmp_path / "source.sqlite"
    con = sqlite3.connect(str(real))
    con.execute("CREATE TABLE users (id TEXT)")
    con.execute("INSERT INTO users VALUES ('u1')")
    con.commit(); con.close()

    monkeypatch.setattr(backups, "backup_dir", lambda: str(tmp_path / "out"))
    monkeypatch.setattr(core, "DB_PATH", str(real))
    monkeypatch.setattr(core, "IS_POSTGRES", False)
    res = backups.run_backup()
    assert res["ok"] is True, res
    assert res["verified"]["ok"] is True
    assert res["verified"]["users"] >= 1


def test_a_corrupt_backup_fails_verification(tmp_path):
    """The failure worth catching looks healthy from the outside."""
    from db import backups
    bad = tmp_path / "medeasy-broken.sqlite"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)   # right magic, junk inside
    check = backups.verify(str(bad))
    assert check["ok"] is False


def test_an_empty_database_is_not_accepted_as_a_backup(tmp_path):
    """A copy of an empty file passes a size check and is worthless."""
    import sqlite3
    from db import backups
    empty = tmp_path / "medeasy-empty.sqlite"
    con = sqlite3.connect(str(empty))
    con.execute("CREATE TABLE users (id TEXT)")
    con.commit(); con.close()
    check = backups.verify(str(empty))
    assert check["ok"] is False and check["reason"] == "no_users"


def test_a_missing_file_is_reported_not_assumed(tmp_path):
    from db import backups
    assert backups.verify(str(tmp_path / "nope.sqlite"))["ok"] is False


def test_status_says_so_when_there_are_no_backups(tmp_path, monkeypatch):
    from db import backups
    monkeypatch.setattr(backups, "backup_dir", lambda: str(tmp_path))
    s = backups.status()
    assert s["has_any"] is False and s["stale"] is True
    assert "reconstructable" in s["note"]


def test_a_fresh_but_unreadable_backup_still_counts_as_stale(tmp_path, monkeypatch):
    """Recency is not health. A file written a minute ago that won't open is
    not cover."""
    from db import backups
    monkeypatch.setattr(backups, "backup_dir", lambda: str(tmp_path))
    (tmp_path / "medeasy-now.sqlite").write_bytes(b"not a database at all")
    s = backups.status()
    assert s["has_any"] is True
    assert s["verified"]["ok"] is False
    assert s["stale"] is True


# ── What changed ────────────────────────────────────────────────────────────

def _event(uid, name, kind, at, detail=""):
    execute("""INSERT INTO medicine_events (id,medicine_id,med_name,kind,detail,at,user_id)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id(), new_id(), name, kind, detail, at, uid), commit=True)


def test_changes_are_reported_as_facts_not_consequences(app):
    from db.reconciliation import changes_between
    c, uid = _register(app, "sec12@medeasy.test")
    with user_context(uid):
        _event(uid, "Metformin", "edited", "2026-08-10T09:00:00", "500mg → 1000mg")
        _event(uid, "Ramipril", "stopped", "2026-08-12T09:00:00")
        out = changes_between("2026-08-01", "2026-08-20")
    kinds = {c_["name"]: c_["kind"] for c_ in out["changes"]}
    assert kinds == {"Metformin": "edited", "Ramipril": "stopped"}
    blob = str(out).lower()
    for word in ("should", "recommend", "concerning", "risk", "dangerous"):
        assert word not in blob, f"the reconciliation interprets: {word!r}"


def test_events_outside_the_window_are_excluded(app):
    from db.reconciliation import changes_between
    c, uid = _register(app, "sec13@medeasy.test")
    with user_context(uid):
        _event(uid, "Old", "started", "2026-01-01T09:00:00")
        _event(uid, "InWindow", "started", "2026-08-15T09:00:00")
        out = changes_between("2026-08-01", "2026-08-20")
    assert [c_["name"] for c_ in out["changes"]] == ["InWindow"]


def test_a_change_on_the_final_day_is_included(app):
    """An appointment on the 20th must see a change made that afternoon."""
    from db.reconciliation import changes_between
    c, uid = _register(app, "sec14@medeasy.test")
    with user_context(uid):
        _event(uid, "LateInDay", "started", "2026-08-20T18:30:00")
        out = changes_between("2026-08-01", "2026-08-20")
    assert [c_["name"] for c_ in out["changes"]] == ["LateInDay"]


def test_restocking_is_not_a_treatment_change(app):
    from db.reconciliation import changes_between
    c, uid = _register(app, "sec15@medeasy.test")
    with user_context(uid):
        _event(uid, "Metformin", "restocked", "2026-08-10T09:00:00")
        out = changes_between("2026-08-01", "2026-08-20")
    assert out["changes"] == []


def test_unchanged_medicines_are_listed_explicitly(app):
    """"Unchanged" is a real answer to the question being asked, and omitting
    them makes the list look shorter than the regimen."""
    from db.reconciliation import changes_between
    c, uid = _register(app, "sec16@medeasy.test")
    c.post("/api/medicines", json={"name": "SteadyMed", "frequency": "once_daily",
                                   "times": ["09:00"]})
    with user_context(uid):
        out = changes_between("2026-08-01", "2026-08-20")
    assert any(m["name"] == "SteadyMed" for m in out["unchanged"])


def test_it_says_what_it_cannot_see(app):
    from db.reconciliation import changes_between
    c, uid = _register(app, "sec17@medeasy.test")
    with user_context(uid):
        out = changes_between("2026-08-01", "2026-08-20")
    assert "do not appear" in out["not_captured"]


def test_the_default_window_anchors_to_the_last_appointment(app):
    from db.reconciliation import since_last_appointment
    c, uid = _register(app, "sec18@medeasy.test")
    c.post("/api/appointments", json={"title": "Diabetes review", "date": "2026-08-05"})
    with user_context(uid):
        out = since_last_appointment()
    assert out["anchor"]["kind"] == "appointment"
    assert out["since"] == "2026-08-05"


def test_with_no_appointment_it_says_which_window_it_used(app):
    from db.reconciliation import since_last_appointment
    c, uid = _register(app, "sec19@medeasy.test")
    with user_context(uid):
        out = since_last_appointment()
    assert out["anchor"]["kind"] == "default_window"
    assert out["since"] and out["until"]


def test_routes_require_auth(app):
    anon = app.test_client()
    for path in ("/api/2fa", "/api/backups", "/api/medicines/changes"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/api/2fa/setup").status_code == 401


# ── Recovery codes can be replaced ──────────────────────────────────────────
# Codes are shown exactly once. Someone who closes that screen too early, or
# burns their last code, otherwise has 2FA on and no way back in when the phone
# dies — so there has to be a way to mint a fresh set.

def test_new_recovery_codes_replace_the_old_ones(app):
    from db import totp as t
    c, uid = _register(app, "sec20@medeasy.test")
    _, first = _enable_2fa(c)
    res = c.post("/api/2fa/recovery-codes", json={"password": PW}).get_json()
    assert res["success"] is True
    second = res["recovery_codes"]
    assert len(second) == t.RECOVERY_CODE_COUNT
    assert set(first).isdisjoint(second), "the same codes were handed out again"
    # An old code must stop working the moment a new set exists, or revoking a
    # leaked set would do nothing.
    with user_context(uid):
        assert t.verify(uid, first[0]) is False, "an old recovery code still works"
        assert t.verify(uid, second[0]) is True


def test_new_recovery_codes_need_the_password(app):
    """These bypass the second factor, so minting them is a security action —
    a borrowed unlocked phone must not be enough."""
    c, uid = _register(app, "sec21@medeasy.test")
    _, first = _enable_2fa(c)
    r = c.post("/api/2fa/recovery-codes", json={"password": "wrong-password"})
    assert r.status_code == 401
    from db import totp as t
    with user_context(uid):
        assert t.verify(uid, first[0]) is True, "the old codes were destroyed anyway"


def test_recovery_codes_are_refused_when_2fa_is_off(app):
    """Issuing credentials for an enrolment nobody confirmed would hand out a
    way in to an account that does not use one."""
    c, uid = _register(app, "sec22@medeasy.test")
    r = c.post("/api/2fa/recovery-codes", json={"password": PW})
    assert r.status_code == 400
    assert r.get_json()["success"] is False
    from db.totp import regenerate_recovery_codes
    with user_context(uid):
        assert regenerate_recovery_codes(uid) == []


def test_regenerating_is_written_to_the_activity_log(app):
    c, uid = _register(app, "sec23@medeasy.test")
    _enable_2fa(c)
    c.post("/api/2fa/recovery-codes", json={"password": PW})
    kinds = [e["kind"] for e in
             c.get("/api/account/activity").get_json()["events"]]
    assert "two_factor_recovery_codes_regenerated" in kinds


def test_new_codes_are_stored_hashed_like_the_first_set(app):
    c, uid = _register(app, "sec24@medeasy.test")
    _enable_2fa(c)
    codes = c.post("/api/2fa/recovery-codes",
                   json={"password": PW}).get_json()["recovery_codes"]
    stored = execute("SELECT recovery FROM user_totp WHERE user_id=?", (uid,),
                     fetchone=True)["recovery"]
    for code in codes:
        assert code not in stored, "a regenerated code is stored in the clear"


# ── Setup hands the UI something scannable ──────────────────────────────────

def test_setup_offers_a_qr_and_degrades_to_the_key(app):
    """Without segno there is no QR, and the panel falls back to typing the key
    in by hand — so `available` has to be reported rather than the QR simply
    being absent."""
    c, uid = _register(app, "sec25@medeasy.test")
    out = c.post("/api/2fa/setup").get_json()
    assert out["secret"] and out["uri"].startswith("otpauth://")
    assert "qr" in out and "available" in out["qr"]
    if out["qr"]["available"]:
        assert out["qr"]["svg"].lstrip().startswith("<?xml") or "<svg" in out["qr"]["svg"]
    else:
        assert out["qr"]["svg"] is None and out["qr"]["reason"]


def test_the_setup_qr_does_not_echo_the_secret_back(app):
    """The QR already carries it. A second plaintext copy in the payload just
    widens where a credential can be read from."""
    c, uid = _register(app, "sec26@medeasy.test")
    out = c.post("/api/2fa/setup").get_json()
    assert "text" not in out["qr"], "the QR payload echoes the otpauth URI back"
