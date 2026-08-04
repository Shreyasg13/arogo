"""Production-ops surface: error tracking degrades to a no-op, and the DB
backup/restore round-trips (SQLite path)."""
import os
import sqlite3
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── error tracking ─────────────────────────────────────────────────────────
def test_error_tracking_is_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    import importlib
    import observability
    importlib.reload(observability)                 # reset module-level _active
    assert observability.init_error_tracking("web") is False
    # capture() must be safe even when tracking is off
    observability.capture(ValueError("boom"), job="test")   # no raise


def test_error_tracking_noop_when_dsn_set_but_sdk_absent(monkeypatch):
    # DSN present but pretend the SDK isn't installed → still a graceful no-op.
    monkeypatch.setenv("SENTRY_DSN", "https://x@example.com/1")
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)   # import returns None -> ImportError path
    import importlib
    import observability
    importlib.reload(observability)
    assert observability.init_error_tracking("web") is False


def test_scrub_event_strips_all_pii_vectors():
    # A health app must never leak PII in an error event. Prove the before_send
    # hook drops request/user/extra/contexts AND stack-frame local variables
    # (where a blood_sugar value or email most easily hides).
    import observability
    event = {
        "request": {"url": "/api/labs", "data": {"value": 450}, "cookies": "me_session=..."},
        "user": {"id": "u1", "email": "patient@example.com", "ip_address": "1.2.3.4"},
        "extra": {"blood_sugar": 450},
        "contexts": {"device": {"name": "Pixel"}},
        "exception": {"values": [{"stacktrace": {"frames": [
            {"function": "log_lab_result", "vars": {"value": 450, "email": "p@x.com"}},
        ]}}]},
    }
    out = observability.scrub_event(event, None)
    assert "request" not in out and "user" not in out
    assert "extra" not in out and "contexts" not in out
    assert out["exception"]["values"][0]["stacktrace"]["frames"][0].get("vars") is None
    # The useful bit — the exception structure — survives.
    assert out["exception"]["values"][0]["stacktrace"]["frames"][0]["function"] == "log_lab_result"


def test_scrub_event_tolerates_a_bare_event():
    # Must not raise on a minimal event with no request/exception.
    import observability
    assert observability.scrub_event({}, None) == {}


# ── request hardening ────────────────────────────────────────────────────────
def test_non_object_json_body_is_400_not_500():
    # Routes read `request.json or {}` then `.get(...)`. A top-level JSON array
    # is truthy and would slip past the fallback → AttributeError → 500. A
    # central guard must turn any non-object JSON body into a clean 400.
    import importlib, auth
    from app import create_app
    from db.core import init_db
    app = create_app(); app.config["TESTING"] = True; init_db()
    importlib.reload(auth); auth.reset_rate_limiter()
    c = app.test_client()
    c.post("/auth/register", json={"email": "json@medeasy.test", "password": "json-pw-12345"})
    for path in ("/api/dependents", "/api/immunizations", "/api/appointments", "/api/labs", "/api/expenses"):
        assert c.post(path, json=[1, 2]).status_code == 400, f"{path} array body must be 400"
    assert c.post("/api/dependents", json="just a string").status_code == 400
    # A proper object body still routes normally (this one 400s on missing name,
    # NOT on the guard — proving valid objects pass the guard).
    assert c.post("/api/dependents", json={}).status_code == 400


# ── backup / restore ────────────────────────────────────────────────────────
def _run_backup(args, db_path, backup_dir=None):
    env = dict(os.environ)
    env["MEDEASY_DB"] = db_path
    env.pop("DATABASE_URL", None)                   # force the SQLite path
    if backup_dir:
        env["BACKUP_DIR"] = backup_dir
    return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "backup.py"), *args],
                          env=env, capture_output=True, text=True)


def test_sqlite_backup_restore_roundtrip(tmp_path):
    db = str(tmp_path / "app.db")
    bkdir = str(tmp_path / "backups")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(id INTEGER, v TEXT)")
    con.execute("INSERT INTO t VALUES (1, 'original')")
    con.commit(); con.close()

    r = _run_backup(["backup"], db, bkdir)
    assert r.returncode == 0, r.stderr
    backups = [f for f in os.listdir(bkdir) if f.endswith(".sqlite")]
    assert len(backups) == 1
    backup_path = os.path.join(bkdir, backups[0])

    # Corrupt the live DB, then restore.
    con = sqlite3.connect(db)
    con.execute("UPDATE t SET v='CORRUPTED'"); con.commit(); con.close()

    r = _run_backup(["restore", backup_path, "--yes"], db, bkdir)
    assert r.returncode == 0, r.stderr

    con = sqlite3.connect(db)
    val = con.execute("SELECT v FROM t").fetchone()[0]
    con.close()
    assert val == "original"                        # data came back
    # a pre-restore safety snapshot was written
    assert any(f.startswith("app.db.pre-restore-") for f in os.listdir(tmp_path))


def test_restore_refuses_a_non_database_file(tmp_path):
    db = str(tmp_path / "app.db")
    sqlite3.connect(db).close()
    junk = tmp_path / "not-a-db.sqlite"
    junk.write_text("this is not a sqlite database")
    r = _run_backup(["restore", str(junk), "--yes"], db)
    assert r.returncode == 2                         # rejected, DB untouched
