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


# ── Threads ─────────────────────────────────────────────────────────────────
# db/core used to hand every thread the same connection, and keep the
# in-transaction flag in a module global. Flask's development server is threaded
# by default and the scheduler runs in a thread of the same process, so this was
# reachable in ordinary use, not a theoretical hazard.

def test_another_threads_committed_write_survives_a_failed_transaction():
    """The original bug, exactly. A request opens a transaction and fails; the
    scheduler commits a heartbeat on its own thread meanwhile. With one shared
    connection the rollback took the scheduler's write with it — silently."""
    import threading, time
    started = threading.Event()
    errors = []

    def background():
        started.wait(5)
        try:
            # SQLite allows one writer at a time, so this blocks on the open
            # transaction and lands the moment it ends — which is exactly the
            # window the old shared connection got wrong.
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("bg", "scheduler"),
                    commit=True)
        except Exception as e:                      # pragma: no cover
            errors.append(e)

    t = threading.Thread(target=background); t.start()
    with pytest.raises(RuntimeError):
        with transaction():
            execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("fg", "request"))
            started.set()
            time.sleep(0.3)                 # let the other thread reach its write
            raise RuntimeError("the request failed")
    t.join(5)

    assert not errors, errors
    # Sharing one connection put the background INSERT inside the foreground's
    # transaction, so the rollback erased it and this was the empty set.
    assert _rows() == {"bg"}, (
        "a failed request must not roll back another thread's committed write")


def test_each_thread_gets_its_own_connection():
    import threading
    from db.core import get_db

    # The connection objects are held, not just their ids, and the threads are
    # kept alive together: once a thread exits its connection is collected and
    # the next one can be allocated at the same address, which makes an id()
    # comparison quietly meaningless.
    conns = []
    lock = threading.Lock()
    at_barrier = threading.Barrier(4, timeout=10)

    def grab():
        c = get_db()
        with lock:
            conns.append(c)
        at_barrier.wait()          # hold the connection open while the others run
        at_barrier.wait()

    main = get_db()
    ts = [threading.Thread(target=grab) for _ in range(3)]
    for t in ts: t.start()
    at_barrier.wait()              # all three now hold a live connection
    try:
        assert len({id(c) for c in conns}) == 3, "threads shared a connection"
        assert id(main) not in {id(c) for c in conns}, \
            "a worker reused the main thread's connection"
    finally:
        at_barrier.wait()
        for t in ts: t.join(5)


def test_threads_still_see_one_database():
    """Per-thread connections must not mean per-thread data — which is exactly
    what a naive fix would produce for an in-memory database."""
    import threading
    execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("from-main", "1"), commit=True)
    out = {}

    def reader():
        out["rows"] = {r["id"] for r in execute("SELECT id FROM _tx_probe", fetchall=True)}
        execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("from-thread", "2"),
                commit=True)

    t = threading.Thread(target=reader); t.start(); t.join(5)
    assert out["rows"] == {"from-main"}, "the thread saw a different database"
    assert _rows() == {"from-main", "from-thread"}, "main can't see the thread's write"


def test_one_threads_transaction_is_invisible_to_another_until_it_commits():
    import threading
    ready, checked = threading.Event(), threading.Event()
    out = {}

    def observer():
        ready.wait(5)
        out["mid"] = {r["id"] for r in execute("SELECT id FROM _tx_probe", fetchall=True)}
        checked.set()

    t = threading.Thread(target=observer); t.start()
    with transaction():
        execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("pending", "1"))
        ready.set()
        checked.wait(5)
    t.join(5)
    assert out["mid"] == set(), "an uncommitted write leaked to another thread"
    assert _rows() == {"pending"}, "and it must be there once committed"


def test_releasing_a_connection_mid_transaction_rolls_it_back():
    """A unit of work that ends without committing did not intend to. Handing
    the next borrower a half-open transaction would corrupt unrelated work."""
    from db.core import release_db
    execute("INSERT INTO _tx_probe (id, note) VALUES (?, ?)", ("before", "1"), commit=True)
    import db.core as core
    conn = core.get_db()
    core._local.in_tx = True
    conn.execute("BEGIN IMMEDIATE") if not core.IS_POSTGRES else None
    execute("DELETE FROM _tx_probe")
    release_db()
    assert _rows() == {"before"}, "an abandoned transaction must not be committed"


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
