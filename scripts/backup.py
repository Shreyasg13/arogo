#!/usr/bin/env python
"""
backup.py — Back up and restore the Arogo database.

Works with either backend, auto-detected the same way the app detects it:
DATABASE_URL set → PostgreSQL, otherwise the SQLite file at MEDEASY_DB.

    python scripts/backup.py backup [--out DIR]      # write a timestamped backup
    python scripts/backup.py list   [--out DIR]      # list existing backups
    python scripts/backup.py restore PATH [--yes]    # restore from a backup

SQLite uses the online backup API, so it is safe to run against a live DB.
PostgreSQL shells out to pg_dump / pg_restore, which must be on PATH (they
ship with the postgresql-client package). See RUNBOOK.md for the drill.

Exit codes: 0 ok, 1 usage/precondition error, 2 backend/tool failure.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys

# Import the app's own backend detection so this never drifts from runtime.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from db.core import DB_PATH, DATABASE_URL, IS_POSTGRES  # noqa: E402

DEFAULT_DIR = os.environ.get("BACKUP_DIR", os.path.join(ROOT, "backups"))


def _stamp():
    # Local time is fine for a filename; the ISO date sorts correctly anyway.
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# ── SQLite ────────────────────────────────────────────────────────────────────
def _backup_sqlite(out_dir):
    import sqlite3
    if not os.path.exists(DB_PATH):
        print(f"error: SQLite DB not found at {DB_PATH}", file=sys.stderr)
        return 1
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"medeasy-{_stamp()}.sqlite")
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        with dst:                       # online backup — consistent snapshot of a live DB
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    print(f"backup ok: {dest}  ({os.path.getsize(dest):,} bytes)")
    return 0


def _restore_sqlite(path, yes):
    import sqlite3
    if not os.path.exists(path):
        print(f"error: backup not found: {path}", file=sys.stderr)
        return 1
    # Validate the backup opens and looks like our DB before touching the live file.
    try:
        c = sqlite3.connect(path)
        n = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        c.close()
    except Exception as e:
        print(f"error: {path} is not a readable SQLite DB ({e})", file=sys.stderr)
        return 2
    if n == 0:
        print(f"error: {path} has no tables — refusing to restore", file=sys.stderr)
        return 2
    print(f"About to OVERWRITE {DB_PATH} with {path} ({n} tables).")
    if not yes and input("Type 'restore' to confirm: ").strip() != "restore":
        print("aborted.")
        return 1
    # Safety net: snapshot the current DB before clobbering it.
    if os.path.exists(DB_PATH):
        pre = f"{DB_PATH}.pre-restore-{_stamp()}"
        shutil.copy2(DB_PATH, pre)
        print(f"saved current DB to {pre}")
    shutil.copy2(path, DB_PATH)
    for ext in ("-wal", "-shm"):        # drop stale journal from the old DB
        stale = DB_PATH + ext
        if os.path.exists(stale):
            os.remove(stale)
    print(f"restore ok: {DB_PATH}")
    return 0


# ── PostgreSQL ─────────────────────────────────────────────────────────────────
def _require(tool):
    if shutil.which(tool) is None:
        print(f"error: '{tool}' not on PATH — install the postgresql-client "
              f"package (RUNBOOK.md).", file=sys.stderr)
        return False
    return True


def _backup_postgres(out_dir):
    if not _require("pg_dump"):
        return 2
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"medeasy-{_stamp()}.dump")
    # -Fc = custom format (compressed, restorable with pg_restore selectivity)
    r = subprocess.run(["pg_dump", "-Fc", "-f", dest, DATABASE_URL])
    if r.returncode != 0:
        print("error: pg_dump failed", file=sys.stderr)
        return 2
    print(f"backup ok: {dest}  ({os.path.getsize(dest):,} bytes)")
    return 0


def _restore_postgres(path, yes):
    if not _require("pg_restore"):
        return 2
    if not os.path.exists(path):
        print(f"error: backup not found: {path}", file=sys.stderr)
        return 1
    print(f"About to restore {path} into the database at DATABASE_URL.")
    print("This DROPS and recreates objects (--clean --if-exists).")
    if not yes and input("Type 'restore' to confirm: ").strip() != "restore":
        print("aborted.")
        return 1
    r = subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner",
                        "-d", DATABASE_URL, path])
    if r.returncode != 0:
        print("error: pg_restore reported errors (some may be benign 'does not "
              "exist' on a fresh DB — verify with a row count)", file=sys.stderr)
        return 2
    print("restore ok")
    return 0


# ── list ───────────────────────────────────────────────────────────────────────
def _list(out_dir):
    if not os.path.isdir(out_dir):
        print(f"(no backups yet in {out_dir})")
        return 0
    files = sorted(f for f in os.listdir(out_dir)
                   if f.startswith("medeasy-") and f.endswith((".sqlite", ".dump")))
    if not files:
        print(f"(no backups yet in {out_dir})")
        return 0
    print(f"backups in {out_dir}:")
    for f in files:
        p = os.path.join(out_dir, f)
        print(f"  {f}  ({os.path.getsize(p):,} bytes)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Back up / restore the Arogo DB.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup"); b.add_argument("--out", default=DEFAULT_DIR)
    sub.add_parser("list").add_argument("--out", default=DEFAULT_DIR)
    r = sub.add_parser("restore")
    r.add_argument("path")
    r.add_argument("--yes", action="store_true", help="skip the confirm prompt")
    args = ap.parse_args(argv)

    backend = "PostgreSQL" if IS_POSTGRES else f"SQLite ({DB_PATH})"
    print(f"[backup] backend: {backend}")

    if args.cmd == "backup":
        return _backup_postgres(args.out) if IS_POSTGRES else _backup_sqlite(args.out)
    if args.cmd == "list":
        return _list(args.out)
    if args.cmd == "restore":
        return (_restore_postgres(args.path, args.yes) if IS_POSTGRES
                else _restore_sqlite(args.path, args.yes))
    return 1


if __name__ == "__main__":
    sys.exit(main())
