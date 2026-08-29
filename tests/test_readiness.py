"""
tests/test_readiness.py — the server-setup report.

Two things matter here and they pull in opposite directions.

It has to be honest: a check that quietly returns "ok" when it cannot tell is
worse than no check, because someone reads the page, believes it, and stops
looking. So every check is exercised against both a configured and an
unconfigured environment, and the report must survive a check that explodes.

And it has to be safe: it reads secrets in order to judge them. A report that
answers "is SECRET_KEY still the default" by returning SECRET_KEY would hand
every session on the install to whoever fetched it. So the last test greps the
whole rendered payload for the values it was given.
"""
import importlib
import json
import os
import re
import uuid

import pytest

import auth as auth_module
from app import create_app
from db import readiness
from db.core import init_db
from db.readiness import CHECKS, DEGRADED, OFF, OK, report

PW = 'ReadyCheck2026!'


@pytest.fixture(scope='module')
def app():
    a = create_app(); a.config['TESTING'] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(app):
    # Unique and lowercase — a reused address collides across test files, and
    # the register route lowercases what it stores.
    c = app.test_client()
    c.post('/auth/register',
           json={'email': f'ready-{uuid.uuid4().hex[:10]}@x.test', 'password': PW})
    return c


# ── The registry is complete ────────────────────────────────────────────────

def test_every_check_declares_the_full_set_of_fields():
    for c in CHECKS:
        for field in ('key', 'name', 'kind', 'check', 'cost', 'fix'):
            assert field in c, f'{c.get("key", c)} has no {field}'
        assert c['kind'] in ('core', 'feature'), c['key']
        assert callable(c['check']), c['key']


def test_no_two_checks_share_a_key():
    keys = [c['key'] for c in CHECKS]
    assert len(keys) == len(set(keys)), f'duplicate keys in CHECKS: {keys}'


@pytest.mark.parametrize('c', CHECKS, ids=lambda c: c['key'])
def test_every_check_says_what_the_gap_costs_and_how_to_close_it(c):
    """The point of the page is not a list of red dots. Someone reading it has
    to learn what breaks for a real person and what to type. A one-word cost
    ("email won't work") is the failure mode this guards against."""
    assert len(c['cost']) > 60, (
        f'{c["key"]}: the cost line does not say what actually happens to '
        f'someone — got {c["cost"]!r}')
    assert len(c['fix']) > 25, f'{c["key"]}: the fix is not actionable'


def _rendered(d):
    """What the client will actually put on screen for a detail."""
    if d is None:
        return ''
    text, args = d['text'], d['args']
    for i, a in enumerate(args, 1):
        text = text.replace(f'%{i}', a)
    return text


@pytest.mark.parametrize('c', CHECKS, ids=lambda c: c['key'])
def test_every_check_returns_a_known_status_and_a_usable_detail(c):
    status, d = c['check']()
    assert status in (OK, OFF, DEGRADED), f'{c["key"]} returned {status!r}'
    if d is None:
        return
    assert set(d) == {'text', 'args'}, f'{c["key"]} detail shape: {d}'
    assert isinstance(d['text'], str) and isinstance(d['args'], list)
    assert all(isinstance(a, str) for a in d['args']), (
        f'{c["key"]} passes a non-string arg — it goes through JSON and then '
        f'straight into the page, so it must already be text')


@pytest.mark.parametrize('c', CHECKS, ids=lambda c: c['key'])
def test_a_detail_template_has_a_slot_for_every_value(c):
    """A template with fewer slots than values silently drops one; more slots
    than values prints a literal %2 at whoever is trying to fix their server."""
    _status, d = c['check']()
    if d is None:
        return
    slots = {int(m) for m in re.findall(r'%(\d)', d['text'])}
    assert slots == set(range(1, len(d['args']) + 1)), (
        f'{c["key"]}: template {d["text"]!r} has slots {sorted(slots)} but '
        f'{len(d["args"])} values')
    assert '%' not in _rendered(d), f'{c["key"]} renders a leftover placeholder'


# ── The report holds together ───────────────────────────────────────────────

def test_the_report_covers_every_registered_check():
    r = report()
    assert [i['key'] for i in r['items']] == [c['key'] for c in CHECKS]
    assert sum(r['counts'].values()) == len(CHECKS)


def test_one_broken_check_does_not_take_the_page_down():
    """The moment a check throws is the moment the other eleven answers matter
    most. Losing all of them to one traceback is the wrong trade."""
    def boom():
        raise RuntimeError('no such host')

    original = CHECKS[0]['check']
    CHECKS[0]['check'] = boom
    try:
        r = report()
        assert len(r['items']) == len(CHECKS)
        assert r['items'][0]['status'] == DEGRADED
        assert 'no such host' in _rendered(r['items'][0]['detail'])
    finally:
        CHECKS[0]['check'] = original


def test_core_problems_lists_only_core_checks_that_are_not_ok():
    r = report()
    by_key = {i['key']: i for i in r['items']}
    for key in r['core_problems']:
        assert by_key[key]['kind'] == 'core'
        assert by_key[key]['status'] != OK
    for i in r['items']:
        if i['kind'] == 'core' and i['status'] != OK:
            assert i['key'] in r['core_problems']


# ── The checks actually read the environment ────────────────────────────────

def test_email_reports_off_when_unconfigured_and_ok_when_set(monkeypatch):
    monkeypatch.setenv('SMTP_HOST', '')
    import mailer
    importlib.reload(mailer)
    assert readiness._check_email()[0] == OFF

    monkeypatch.setenv('SMTP_HOST', 'smtp.example.com')
    monkeypatch.setenv('SMTP_PORT', '587')
    importlib.reload(mailer)
    status, d = readiness._check_email()
    assert status == OK and 'smtp.example.com' in _rendered(d)

    # STARTTLS off is not the same as unconfigured, and must not read as fine.
    monkeypatch.setenv('SMTP_TLS', '0')
    importlib.reload(mailer)
    assert readiness._check_email()[0] == DEGRADED
    monkeypatch.delenv('SMTP_TLS')
    importlib.reload(mailer)


def test_the_shipped_default_secret_is_reported_as_not_set(monkeypatch):
    """The whole point: a default that works is indistinguishable from a real
    one until someone forges a cookie with it."""
    import config
    monkeypatch.setattr(config.Config, 'SECRET_KEY',
                        'dev-secret-change-in-production')
    assert readiness._check_secret_key()[0] == OFF

    monkeypatch.setattr(config.Config, 'SECRET_KEY', 'a' * 64)
    assert readiness._check_secret_key()[0] == OK

    # Set, but too short to be worth much — reported, not waved through.
    monkeypatch.setattr(config.Config, 'SECRET_KEY', 'abc123')
    assert readiness._check_secret_key()[0] == DEGRADED


def test_a_missing_backup_directory_is_not_reported_as_merely_empty(tmp_path,
                                                                   monkeypatch):
    """"No backups yet" and "cannot write backups" look identical from outside
    and are very different problems. Reporting them the same way hides one."""
    monkeypatch.setenv('BACKUP_DIR', str(tmp_path / 'nope'))
    status, d = readiness._check_backups()
    assert status == OFF and 'does not exist' in d['text']

    d = tmp_path / 'backups'
    d.mkdir()
    monkeypatch.setenv('BACKUP_DIR', str(d))
    status, d = readiness._check_backups()
    assert status == DEGRADED and 'no backups yet' in d['text']


@pytest.mark.parametrize('age_h,expect', [
    (0.2,  'under an hour ago'),
    (1.0,  'an hour ago'),
    (5.0,  '5 hours ago'),
    (26.0, '26 hours ago'),
    (30.0, '30 hours ago'),
])
def test_every_backup_age_branch_renders(tmp_path, monkeypatch, age_h, expect):
    """Each branch is exercised, not only the one today's environment happens
    to hit. A template broken in an unvisited branch went green exactly that
    way: the check passed because the real backup was an hour old."""
    import time
    d = tmp_path / 'backups'
    d.mkdir()
    f = d / 'medeasy-20260101-000000.sqlite'
    f.write_bytes(b'x')
    when = time.time() - age_h * 3600
    os.utime(f, (when, when))
    monkeypatch.setenv('BACKUP_DIR', str(d))
    _status, det = readiness._check_backups()
    assert expect in _rendered(det), f'{age_h}h rendered {_rendered(det)!r}'


def test_a_detail_with_the_wrong_number_of_values_is_refused():
    """The validation lives in detail() rather than only in a test, so it fires
    on whichever branch actually runs."""
    with pytest.raises(ValueError):
        readiness.detail('%1 kept, newest %2 hours ago', 3)      # missing %2
    with pytest.raises(ValueError):
        readiness.detail('nothing to fill', 'spare')             # no slot
    # And the correct shape is accepted.
    assert readiness.detail('%1 of %2', 1, 2)['args'] == ['1', '2']


def test_a_stale_backup_is_not_reported_as_a_good_one(tmp_path, monkeypatch):
    import time
    from db.backups import STALE_AFTER_HOURS
    d = tmp_path / 'backups'
    d.mkdir()
    old = d / 'medeasy-20200101-000000.sqlite'
    old.write_bytes(b'x')
    stale = time.time() - (STALE_AFTER_HOURS + 24) * 3600
    os.utime(old, (stale, stale))
    monkeypatch.setenv('BACKUP_DIR', str(d))
    assert readiness._check_backups()[0] == DEGRADED


def test_low_disk_is_flagged_before_writes_start_failing(monkeypatch):
    import shutil as sh
    from collections import namedtuple
    Usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(sh, 'disk_usage',
                        lambda p: Usage(0, 0, 50 * 1024 * 1024))
    assert readiness._check_disk()[0] == DEGRADED
    monkeypatch.setattr(sh, 'disk_usage',
                        lambda p: Usage(0, 0, 40 * 1024 ** 3))
    status, d = readiness._check_disk()
    assert status == OK and 'GB' in _rendered(d)


# ── It must not leak what it inspects ───────────────────────────────────────

SECRETS = {
    'SECRET_KEY': 'topsecret' + 'k' * 55,
    'SMTP_PASS': 'smtp-password-do-not-print',
    'TWILIO_AUTH_TOKEN': 'twilio-token-do-not-print',
    'VAPID_PRIVATE_KEY': 'vapid-private-do-not-print',
}


def test_the_report_never_returns_a_secret_it_read(monkeypatch):
    """This check exists because the honest way to answer "is the secret still
    the default" is to compare against the secret — and the lazy way to show
    your work is to include it."""
    import config
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config.Config, 'SECRET_KEY', SECRETS['SECRET_KEY'])

    payload = json.dumps(report())
    for name, value in SECRETS.items():
        assert value not in payload, f'{name} appears in the readiness report'
        # Also refuse a partial: a prefix long enough to brute-force from.
        assert value[:16] not in payload, f'{name} is partly exposed'


def test_the_report_is_json_serialisable():
    """It is returned by jsonify; a stray Path or datetime would 500 the page."""
    json.dumps(report())


# ── The route ───────────────────────────────────────────────────────────────

def test_readiness_needs_a_session(client):
    assert client.get('/api/server/readiness').status_code == 401


def test_readiness_route_returns_the_report(auth_client):
    r = auth_client.get('/api/server/readiness')
    assert r.status_code == 200
    body = r.get_json()
    assert len(body['items']) == len(CHECKS)
    assert set(body['counts']) == {OK, DEGRADED, OFF}
    for i in body['items']:
        assert i['cost'] and i['fix']
