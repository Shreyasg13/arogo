"""
scripts/sandbox.py — point this process at a throwaway database.

Import and call this FIRST, before anything that reaches db.core:

    from scripts.sandbox import use_throwaway_db
    use_throwaway_db()                 # now safe
    from app import create_app         # noqa: E402

Why it exists: a one-off script written to check a change end-to-end imported
the app, registered a user and wrote fixture rows into the real database. The
rows were removed, but "remember to set MEDEASY_DB" is not a safeguard — it is
a thing to forget, and it was forgotten.

The important part is not the setenv, which anyone can write. It is the check
that db.core has NOT already been imported. That module reads DB_PATH once, at
import time, so setting the variable afterwards looks like it worked and does
nothing at all — which is precisely the mistake this is here to stop. That case
raises rather than warns: a script that thinks it is sandboxed and is not is
more dangerous than one that never tried.
"""
from __future__ import annotations

import os
import sys
import tempfile


class LiveDatabaseRisk(RuntimeError):
    """Raised when sandboxing came too late to have any effect."""


def use_throwaway_db(name: str = 'arogo-sandbox', fresh: bool = True) -> str:
    """Send this process's database writes to a temporary file. Returns its path.

    `fresh` deletes any previous file of the same name, so a script gets a clean
    database rather than yesterday's leftovers.
    """
    if 'db.core' in sys.modules:
        raise LiveDatabaseRisk(
            'db.core is already imported, so it has already read DB_PATH and '
            'setting MEDEASY_DB now would change nothing — this process would '
            'keep writing to whatever it opened. Call use_throwaway_db() '
            'before importing app or db.')

    path = os.path.join(tempfile.gettempdir(), f'{name}.db')
    if fresh:
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(path + suffix)
            except OSError:
                pass
    os.environ['MEDEASY_DB'] = path
    # A DATABASE_URL in the environment wins over MEDEASY_DB in db.core, so a
    # sandbox that left it set would quietly write to the real PostgreSQL.
    os.environ.pop('DATABASE_URL', None)
    return path


def assert_not_live() -> None:
    """Refuse to continue if this process is pointed at the real database.

    For a script that does its own sandboxing and wants to prove it worked.
    """
    from db.core import DB_PATH, IS_LIVE_DB
    if IS_LIVE_DB:
        raise LiveDatabaseRisk(
            f'this process is using the real database ({DB_PATH}). Set '
            f'MEDEASY_DB to a throwaway file before importing db.core.')
