"""
conftest.py — Pytest configuration.

Sets MEDEASY_DB=:memory: before any import so every test runs against a fresh
in-memory SQLite instance.

Set DATABASE_URL to run the same suite against PostgreSQL, which is the
documented production backend and disagrees with SQLite in ways that pass
silently here — most importantly, PostgreSQL aborts an entire transaction on any
statement error. CI runs both.
"""
import os

import pytest

os.environ["MEDEASY_DB"] = ":memory:"

_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_IS_PG = _DATABASE_URL.startswith(("postgres://", "postgresql://"))


def pytest_configure(config):
    """Refuse to run against a PostgreSQL database that isn't obviously a test one.

    The suite registers users, writes health records and drops the schema between
    runs. Someone with DATABASE_URL exported for a real deployment — the ordinary
    state of a shell on the server — would otherwise erase it just by typing
    `pytest`. Requiring "test" in the database name costs nothing and makes that
    accident impossible.
    """
    if not _IS_PG:
        return
    dbname = _DATABASE_URL.rsplit("/", 1)[-1].split("?")[0].lower()
    if "test" not in dbname:
        raise pytest.UsageError(
            f"Refusing to run the test suite against PostgreSQL database "
            f"{dbname!r}: the suite drops and recreates the schema. Point "
            f"DATABASE_URL at a database whose name contains 'test'."
        )


if _IS_PG:
    @pytest.fixture(scope="session", autouse=True)
    def _fresh_postgres_schema():
        """One clean schema per run.

        Each SQLite worker gets its own private :memory: database; on PostgreSQL
        every test shares one, and leftovers from a previous run would show up as
        failures that look like real bugs. The name guard in pytest_configure has
        already established this database is disposable.
        """
        from db.core import execute, init_db
        execute("DROP SCHEMA IF EXISTS public CASCADE")
        execute("CREATE SCHEMA public")
        init_db()
        yield
