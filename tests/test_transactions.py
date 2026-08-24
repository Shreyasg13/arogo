"""transaction() and savepoint() — the primitives a restore depends on.

These matter far beyond their size. A restore deletes the user's rows before
inserting the backup's, so "half of it worked" is worse than "none of it did";
and the per-row skip that keeps one malformed row from killing a 4,000-row
restore only works if a failed statement is genuinely recoverable.

That second property is where SQLite and PostgreSQL diverge sharply. PostgreSQL
aborts the ENTIRE transaction on any statement error — after one failed INSERT
every later statement returns "current transaction is aborted" — so the familiar
try/except-and-continue silently loses the rest of the batch there while passing
every test on SQLite. savepoint() is the portable fix, and because both backends
implement SAVEPOINT identically these tests exercise the real mechanism rather
than a SQLite-only approximation.
"""
import pytest

from db.core import init_db, execute, transaction, savepoint


@pytest.fixture(scope="module", autouse=True)
def _db():
    init_db()
    execute("""CREATE TABLE IF NOT EXISTS _tx_probe (
                 id TEXT PRIMARY KEY, note TEXT)""", commit=True)
    yield
    try:
        execute("DROP TABLE IF EXISTS _tx_probe", commit=True)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clean():
    execute("DELETE FROM _tx_probe", commit=True)
    yield


def _rows():
    return {r["id"] for r in execute("SELECT id FROM _tx_probe", fetchall=True)}


# ── transaction ─────────────────────────────────────────────────────────────

def test_commit_persists_every_statement():
    with transaction():
        execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("a", "1"))
        execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("b", "2"))
    assert _rows() == {"a", "b"}


def test_an_exception_rolls_everything_back():
    with pytest.raises(RuntimeError):
        with transaction():
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("a", "1"))
            execute("DELETE FROM _tx_probe WHERE id=?", ("a",))
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("b", "2"))
            raise RuntimeError("disk went away")
    assert _rows() == set(), "a rolled-back block must leave nothing behind"


def test_a_rollback_restores_rows_deleted_inside_the_block():
    """The restore case exactly: delete first, insert second, fail. The deleted
    rows must come back."""
    execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("keep", "original"),
            commit=True)
    with pytest.raises(RuntimeError):
        with transaction():
            execute("DELETE FROM _tx_probe")
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("new", "x"))
            raise RuntimeError("boom")
    assert _rows() == {"keep"}


def test_nesting_joins_the_outer_block_instead_of_committing_early():
    """An inner transaction() must not commit — otherwise a helper that wants
    atomicity would silently break its caller's."""
    with pytest.raises(RuntimeError):
        with transaction():
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("outer", "1"))
            with transaction():
                execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("inner", "2"))
            raise RuntimeError("boom after the inner block closed")
    assert _rows() == set(), "the inner block must not have committed on its own"


def test_writes_are_normal_again_after_a_transaction():
    with transaction():
        execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("a", "1"))
    execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("b", "2"), commit=True)
    assert _rows() == {"a", "b"}, "autocommit must be restored afterwards"


def test_autocommit_is_restored_even_when_the_block_fails():
    with pytest.raises(RuntimeError):
        with transaction():
            raise RuntimeError("boom")
    execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("after", "1"), commit=True)
    assert _rows() == {"after"}


# ── savepoint ───────────────────────────────────────────────────────────────

def test_a_failed_step_is_skipped_and_the_rest_still_land():
    """The behaviour a restore relies on. On PostgreSQL a bare try/except here
    would lose every row after the first failure."""
    with transaction():
        for i, dup in enumerate(["a", "b", "a", "c"]):   # the third collides
            with savepoint() as sp:
                execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", (dup, str(i)))
            if not sp.ok:
                continue
    assert _rows() == {"a", "b", "c"}, "a duplicate must not kill the rows after it"


def test_savepoint_reports_failure_rather_than_raising():
    with transaction():
        with savepoint() as sp:
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("a", "1"))
        assert sp.ok is True
        with savepoint() as sp2:
            execute("INSERT INTO nonexistent_table_xyz (id) VALUES (?)", ("x",))
        assert sp2.ok is False, "the caller decides what a failure means"
    assert _rows() == {"a"}


def test_a_failed_savepoint_undoes_only_its_own_work():
    with transaction():
        with savepoint():
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("keeper", "1"))
        with savepoint() as sp:
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("doomed", "2"))
            raise RuntimeError("this step failed after writing")
        assert sp.ok is False
    assert _rows() == {"keeper"}, "only the failed step should be undone"


def test_an_outer_rollback_still_discards_committed_savepoints():
    """Releasing a savepoint is not a commit — the outer transaction still owns
    the outcome."""
    with pytest.raises(RuntimeError):
        with transaction():
            with savepoint():
                execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("a", "1"))
            raise RuntimeError("boom")
    assert _rows() == set()


def test_savepoint_outside_a_transaction_is_a_no_op_that_still_reports():
    with savepoint() as sp:
        execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("a", "1"), commit=True)
    assert sp.ok is True
    with savepoint() as sp2:
        execute("INSERT INTO nonexistent_table_xyz (id) VALUES (?)", ("x",))
    assert sp2.ok is False
    assert _rows() == {"a"}


def test_nested_savepoints_get_distinct_names():
    """Reusing a name would make the inner RELEASE close the outer one."""
    with transaction():
        with savepoint():
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("outer", "1"))
            with savepoint() as inner:
                execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("outer", "dup"))
            assert inner.ok is False
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("after", "2"))
    assert _rows() == {"outer", "after"}
