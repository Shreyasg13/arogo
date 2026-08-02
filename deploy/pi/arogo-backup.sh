#!/usr/bin/env bash
# Nightly Arogo backup — a consistent snapshot of the SQLite database, even
# while the app is running (uses SQLite's online-backup API via the app's own
# Python, so it needs no extra packages). Keeps 14 days, gzipped.
#
# Install: see deploy/pi/ in DEPLOY.md. Runs from arogo-backup.timer.
# If you moved to PostgreSQL, replace the snapshot line with a pg_dump instead.
set -euo pipefail

APP_DIR="${AROGO_DIR:-/home/pi/arogo}"
DB="$APP_DIR/medeasy.db"
DEST="${AROGO_BACKUP_DIR:-/home/pi/arogo-backups}"
KEEP_DAYS="${AROGO_BACKUP_KEEP_DAYS:-14}"

mkdir -p "$DEST"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$DEST/medeasy-$stamp.db"

if [ ! -f "$DB" ]; then
  echo "arogo-backup: no database at $DB — nothing to back up" >&2
  exit 0
fi

# Online, crash-consistent snapshot (safe while the web/scheduler are writing).
"$APP_DIR/.venv/bin/python" - "$DB" "$out" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dst)
with d:
    s.backup(d)          # SQLite online backup — a coherent copy, no locking games
s.close(); d.close()
PY

gzip -f "$out"
echo "arogo-backup: wrote $out.gz"

# Rotate: drop snapshots older than KEEP_DAYS.
find "$DEST" -name 'medeasy-*.db.gz' -mtime "+$KEEP_DAYS" -delete
