"""
tests/test_live_db_guard.py — keeping scaffolding out of the real database.

A one-off script written to check a change end-to-end imported the app,
registered e2e-…@x.test and wrote fixture rows straight into the live database.
The rows were removed, but nothing had stopped it and nothing would have said
so afterwards either.

"Remember to set MEDEASY_DB" is not a safeguard; it is a thing to forget. Three
mechanisms replace it, and this file holds them to their promises:

  * The app refuses to register a reserved test domain against the real
    database — the harm itself, blocked.
  * A process that is not the server says out loud that it has opened real
    health records, instead of printing a path nobody reads.
  * scripts/sandbox.py makes the safe path one line, and raises rather than
    warns when it is called too late to work.
"""
import importlib
import io
import os
import re
import sys
import uuid

import pytest

import auth as auth_module
from app import create_app
from db.core import init_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = 'LiveGuard2026!'


@pytest.fixture(scope='module')
def app():
    a = create_app(); a.config['TESTING'] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


# ── The refusal ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('email', [
    'e2e-abc@x.test',                 # the address that actually did this
    'scale@bench.test',
    'someone@example.invalid',
    'dev@my.localhost',
    'qa@thing.example',
])
def test_a_reserved_test_domain_is_refused_on_the_real_database(email, monkeypatch):
    """These TLDs are reserved by RFC 2606/6761 and can never be real, so
    refusing them costs nobody an account."""
    import routes.auth as routes_auth
    monkeypatch.setattr('db.core.IS_LIVE_DB', True)
    assert routes_auth._reserved_test_domain(email)


@pytest.mark.parametrize('email', [
    'ayush@gmail.com', 'someone@nhs.uk', 'a.b+c@sub.domain.co.in',
    'person@testing.com',             # "test" in the name is not a reserved TLD
])
def test_a_real_address_is_never_refused(email, monkeypatch):
    import routes.auth as routes_auth
    monkeypatch.setattr('db.core.IS_LIVE_DB', True)
    assert routes_auth._reserved_test_domain(email) is None


def test_the_refusal_does_not_apply_off_the_live_database():
    """The suite runs in memory and benchmarks use their own file. A guard that
    blocked those would be turned off within a day, and then it guards nothing.
    """
    import routes.auth as routes_auth
    from db.core import IS_LIVE_DB
    assert not IS_LIVE_DB, 'the test suite must never run on the live database'
    assert routes_auth._reserved_test_domain('e2e@x.test') is None


def test_registration_still_works_for_test_addresses_in_the_suite(app):
    """The two thousand tests in this repository register .test addresses."""
    c = app.test_client()
    r = c.post('/auth/register',
               json={'email': f'guard-{uuid.uuid4().hex[:8]}@x.test', 'password': PW})
    assert r.status_code in (200, 201), r.get_json()


def test_the_route_returns_the_refusal_when_live(app, monkeypatch):
    monkeypatch.setattr('db.core.IS_LIVE_DB', True)
    r = app.test_client().post(
        '/auth/register', json={'email': 'e2e-x@x.test', 'password': PW})
    assert r.status_code == 400
    assert 'reserved test domain' in r.get_json()['error']


# ── Knowing which database this is ──────────────────────────────────────────

def test_is_live_db_is_false_for_a_throwaway_file():
    """A benchmark pointing at its own file is doing the right thing and must
    not be obstructed — the flag is about the REAL database, not about files."""
    from db import core
    assert core.IS_LIVE_DB is False
    assert os.path.abspath(core.DB_PATH) != os.path.abspath(core.DEFAULT_DB_PATH)


def test_the_warning_stays_quiet_for_the_server_itself():
    """The server saying "you are using your database" every boot is noise, and
    noise gets ignored — which is exactly how the old path banner failed."""
    from db import core
    src = io.open(os.path.join(ROOT, 'db', 'core.py'), encoding='utf-8').read()
    body = src[src.index('def _warn_if_live_and_probably_a_script'):]
    body = body[:body.index('\n\n\n')] if '\n\n\n' in body else body
    for entry in ('app.py', 'run_scheduler.py'):
        assert entry in body, f'{entry} is not exempted from the warning'
    assert 'IS_LIVE_DB' in body


# ── The sandbox helper ──────────────────────────────────────────────────────

def test_sandboxing_after_db_core_is_imported_raises():
    """The mistake this exists to stop. db.core reads DB_PATH once at import,
    so a late setenv looks like it worked and does nothing — a script that
    believes it is sandboxed and is not is worse than one that never tried."""
    sys.path.insert(0, ROOT)
    from scripts.sandbox import LiveDatabaseRisk, use_throwaway_db
    assert 'db.core' in sys.modules, 'precondition: db.core is already imported'
    with pytest.raises(LiveDatabaseRisk):
        use_throwaway_db()


def test_assert_not_live_passes_here_and_would_raise_on_the_real_database(monkeypatch):
    sys.path.insert(0, ROOT)
    from scripts.sandbox import LiveDatabaseRisk, assert_not_live
    assert_not_live()                       # in-memory suite: fine
    monkeypatch.setattr('db.core.IS_LIVE_DB', True)
    with pytest.raises(LiveDatabaseRisk):
        assert_not_live()


# ── Every script has made a decision ────────────────────────────────────────

# Scripts that legitimately operate on the real database, and why. Anything
# else that reaches db.core must sandbox itself — a script that simply forgot
# is indistinguishable from one that meant it, which is how this started.
LIVE_DB_SCRIPTS = {
    'backup.py': 'backing up the real database is the entire point of it',
    'create_user.py': 'creates an account on the real server, deliberately',
    'gen_api_docs.py': 'builds the app to read its route map; writes nothing',
    'sandbox.py': 'the helper itself — it must import db.core to check',
}


def test_every_script_that_touches_the_database_has_a_decision():
    scripts = os.path.join(ROOT, 'scripts')
    undecided = []
    for name in sorted(os.listdir(scripts)):
        if not name.endswith('.py') or name.startswith('_'):
            continue
        src = io.open(os.path.join(scripts, name), encoding='utf-8').read()
        if not re.search(r'^\s*(from|import)\s+(app|db)\b', src, re.M):
            continue                       # never reaches a database
        if name in LIVE_DB_SCRIPTS:
            continue
        sandboxed = ('use_throwaway_db' in src
                     or re.search(r"environ\[['\"]MEDEASY_DB", src))
        if not sandboxed:
            undecided.append(name)
    assert not undecided, (
        'these scripts reach the database without sandboxing themselves or '
        'being listed in LIVE_DB_SCRIPTS with a reason: ' + ', '.join(undecided))


def test_the_live_db_script_list_is_not_stale():
    scripts = os.path.join(ROOT, 'scripts')
    for name, why in LIVE_DB_SCRIPTS.items():
        assert os.path.exists(os.path.join(scripts, name)), f'{name} is gone'
        assert len(why) > 25, f'{name} is listed without a real reason'


def test_the_sandbox_sets_the_variable_before_anything_reads_it():
    """A sandbox that leaves DATABASE_URL set would quietly write to the real
    PostgreSQL instead, MEDEASY_DB or not."""
    src = io.open(os.path.join(ROOT, 'scripts', 'sandbox.py'), encoding='utf-8').read()
    assert "environ['MEDEASY_DB']" in src
    assert "pop('DATABASE_URL'" in src
