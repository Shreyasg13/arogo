"""Backups that actually happen, and that are known to be readable.

scripts/backup.py has existed for a while and nothing ever ran it, so backups
were a thing the operator meant to do. On a Raspberry Pi the SD card is the
single most likely component to fail, and a medication history is not
reconstructable from anywhere else.

Two jobs here, and the second matters more than it sounds:

  Run it, nightly, from the scheduler.

  VERIFY it. A file existing in a backups directory is not a backup — it is a
  file. Every run opens the copy it just made, checks SQLite's own integrity
  check passes, and confirms the tables are actually there with rows in them.
  A backup that has never been read is a guess, and the moment it matters is the
  moment there is nothing left to compare it against.

Everything reported is measured. Where a figure can't be read it is None and the
page shows "unknown", never a zero that reads as "fine".
"""
import datetime as dt
import os

# Keep enough history to survive noticing a problem late — a corruption that
# went unnoticed for a week is exactly the case a single rolling backup loses.
KEEP_BACKUPS = 14

# Past this, the newest good backup is old enough to say so out loud.
STALE_AFTER_HOURS = 48


def backup_dir():
    from db.core import ROOT_DIR
    return os.environ.get('BACKUP_DIR', os.path.join(ROOT_DIR, 'backups'))


def _files():
    d = backup_dir()
    out = []
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.is_file() and e.name.startswith('medeasy-'):
                    try:
                        st = e.stat()
                        out.append({'name': e.name, 'path': e.path,
                                    'bytes': st.st_size, 'mtime': st.st_mtime})
                    except OSError:
                        pass
    except OSError:
        return []
    return sorted(out, key=lambda f: -f['mtime'])


def verify(path) -> dict:
    """Open a backup and prove it is usable.

    Not just "does the file exist": PRAGMA integrity_check, then a count on a
    table that must never be empty in a real install. A truncated or half-written
    copy passes a size check and fails both of these.
    """
    if not os.path.exists(path):
        return {'ok': False, 'reason': 'missing'}
    try:
        import sqlite3
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            res = con.execute('PRAGMA integrity_check').fetchone()
            if not res or str(res[0]).lower() != 'ok':
                return {'ok': False, 'reason': 'integrity_check_failed'}
            # A backup of an install with no users is almost certainly a copy of
            # an empty file, which is the failure mode worth catching: it looks
            # exactly like a healthy backup from the outside.
            users = con.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            tables = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            con.close()
    except Exception as e:
        return {'ok': False, 'reason': 'unreadable', 'error': type(e).__name__}
    if users < 1:
        return {'ok': False, 'reason': 'no_users', 'tables': tables}
    return {'ok': True, 'users': users, 'tables': tables}


def run_backup(prune: bool = True) -> dict:
    """Take a backup, verify it, and discard the copy if it doesn't verify.

    Keeping a backup that failed verification would be worse than not taking
    one — it makes the directory listing look healthy.
    """
    from db.core import IS_POSTGRES
    if IS_POSTGRES:
        # pg_dump is the right tool and needs a binary this module can't assume.
        # Reported honestly rather than silently doing nothing.
        return {'ok': False, 'reason': 'postgres_needs_pg_dump',
                'note': 'Use scripts/backup.py, which shells out to pg_dump.'}
    import sqlite3
    from db.core import DB_PATH
    if not DB_PATH or DB_PATH == ':memory:' or not os.path.exists(DB_PATH):
        return {'ok': False, 'reason': 'no_database_file'}

    d = backup_dir()
    os.makedirs(d, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = os.path.join(d, f'medeasy-{stamp}.sqlite')
    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)          # consistent snapshot of a live database
        finally:
            src.close()
            dst.close()
    except Exception as e:
        return {'ok': False, 'reason': 'copy_failed', 'error': type(e).__name__}

    check = verify(dest)
    if not check['ok']:
        try:
            os.remove(dest)              # never leave an unverified copy behind
        except OSError:
            pass
        return {'ok': False, 'reason': 'verify_failed', 'detail': check}

    removed = _prune() if prune else 0
    return {'ok': True, 'path': dest, 'name': os.path.basename(dest),
            'bytes': os.path.getsize(dest), 'verified': check, 'pruned': removed}


def _prune() -> int:
    """Drop the oldest beyond KEEP_BACKUPS. Only ever removes files this module
    would have written — the name prefix is the guard."""
    files = _files()
    removed = 0
    for f in files[KEEP_BACKUPS:]:
        try:
            os.remove(f['path'])
            removed += 1
        except OSError:
            pass
    return removed


# How long a copy off this machine stays fresh enough to count. Deliberately
# generous: nagging someone weekly about a backup is how they learn to ignore
# the message, and a month-old copy of a medication history is still worth
# vastly more than nothing.
OFFSITE_STALE_DAYS = 30


def offsite_status() -> dict:
    """When the user last took a copy OFF this machine.

    The on-disk backups are the important half of the story and the misleading
    half. They survive a mistake — a bad restore, a deleted record — and they do
    not survive the one failure that is actually likely on a Raspberry Pi: the
    SD card dying, or the box being lost or stolen. Both copies are on the same
    card. Saying "backed up and verified" without saying that would be true and
    would leave someone believing the wrong thing.

    Read from the account activity log rather than tracked separately, because
    that log already records every download and cannot be edited.

    Returns has_any=False rather than a guess when nothing is recorded — a user
    who downloaded a copy before this log existed is told there's no record, not
    told they never did it.
    """
    from .core import execute, current_user_id
    row = execute("""SELECT at FROM security_events
                     WHERE user_id=? AND kind IN ('backup_downloaded', 'export_downloaded')
                     ORDER BY at DESC LIMIT 1""",
                  (current_user_id(),), fetchone=True)
    if not row or not row['at']:
        return {'has_any': False, 'last_at': None, 'age_days': None,
                'stale': True, 'stale_after_days': OFFSITE_STALE_DAYS,
                'note': 'No record of a copy taken off this server. Backups on '
                        'the server survive a mistake; they do not survive the '
                        'server.'}
    try:
        when = dt.datetime.fromisoformat(str(row['at']))
    except ValueError:
        # An unparseable timestamp is unknown, not zero. Reporting "0 days ago"
        # from a broken value would be the most reassuring possible lie.
        return {'has_any': True, 'last_at': str(row['at']), 'age_days': None,
                'stale': True, 'stale_after_days': OFFSITE_STALE_DAYS,
                'note': 'A copy was downloaded, but the date could not be read.'}
    age_days = (dt.datetime.now() - when).days
    return {'has_any': True, 'last_at': when.isoformat(),
            'age_days': age_days,
            'stale': age_days > OFFSITE_STALE_DAYS,
            'stale_after_days': OFFSITE_STALE_DAYS}


def status() -> dict:
    """How healthy the backups are, from what is on disk.

    The newest file is verified on every call rather than trusted, because the
    only thing worse than no backup is one everybody believes in.
    """
    files = _files()
    if not files:
        return {'has_any': False, 'count': 0, 'newest': None, 'stale': True,
                'verified': None, 'directory': backup_dir(),
                'note': 'No backups found. On a Pi the SD card is the most '
                        'likely thing to fail, and none of this is '
                        'reconstructable from anywhere else.'}
    newest = files[0]
    check = verify(newest['path'])
    age_h = (dt.datetime.now().timestamp() - newest['mtime']) / 3600.0
    return {
        'has_any': True,
        'count': len(files),
        'directory': backup_dir(),
        'newest': {'name': newest['name'], 'bytes': newest['bytes'],
                   'taken_at': dt.datetime.fromtimestamp(newest['mtime']).isoformat(),
                   'age_hours': round(age_h, 1)},
        'verified': check,
        # Stale OR unverifiable both count as "not covered" — a fresh file that
        # won't open is not a backup.
        'stale': (age_h > STALE_AFTER_HOURS) or not check['ok'],
        'stale_after_hours': STALE_AFTER_HOURS,
        'total_bytes': sum(f['bytes'] for f in files),
        'keep': KEEP_BACKUPS,
    }
