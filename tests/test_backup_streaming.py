"""
tests/test_backup_streaming.py — the backup download, without holding it all.

Measured on twenty years of daily logging (73,000 dose logs, a 22 MB database):
building the backup as a dict peaked at 93 MB, and json.dumps(indent=2) on top
of that peaked at 228 MB to produce a 28 MB file. Ten times the size of the
database, in RAM, on a Raspberry Pi — during the one operation you cannot
afford to have fail.

The risk in fixing it is worse than the bug: a streamed file that differs from
the assembled one, even in whitespace, is a backup that a restore might not
read. So the first and most important test is that the two are identical.
"""
import json
import uuid

import pytest

import auth as auth_module
from app import create_app
from db.account import export_all_data, stream_all_data
from db.core import execute, init_db, new_id, now_iso, user_context

PW = 'Streaming2026!'


@pytest.fixture(scope='module')
def app():
    a = create_app(); a.config['TESTING'] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _user(app, seed=True):
    email = f'stream-{uuid.uuid4().hex[:10]}@x.test'
    c = app.test_client()
    c.post('/auth/register', json={'email': email, 'password': PW})
    uid = dict(execute('SELECT id FROM users WHERE email=?', (email,),
                       fetchone=True))['id']
    if seed:
        with user_context(uid):
            mid = new_id()
            execute("""INSERT INTO medicines (id,name,dosage,unit,frequency,times,
                                              active,created_at,user_id,notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (mid, 'Metformin "500"', '500', 'mg', 'once_daily',
                     '["09:00"]', 1, now_iso(), uid,
                     'quotes " and \\ backslash and \nnewline'), commit=True)
            for i in range(40):
                execute("""INSERT INTO dose_logs (id,user_id,medicine_id,date_key,
                                                  time_key,taken,taken_at)
                           VALUES (?,?,?,?,?,?,?)""",
                        (new_id(), uid, mid, f'2026-07-{i % 28 + 1:02d}', '09:00',
                         1 if i % 5 != 0 else 0, now_iso()), commit=True)
            execute("""INSERT INTO symptoms (id,name,severity,date_key,time_of_day,
                                             notes,logged_at,user_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (new_id(), 'Головная боль ☹', 6, '2026-07-04', 'morning',
                     'unicode, emoji 💊, and a comma, inside', now_iso(), uid),
                    commit=True)
    return c, uid


def _streamed(uid):
    return ''.join(stream_all_data(uid))


# ── The file has to be the same file ────────────────────────────────────────

def test_the_streamed_backup_is_byte_identical_to_the_assembled_one(app):
    """The whole point. A restore reads files written by either version, and a
    difference in whitespace alone would be a backup you cannot trust."""
    _c, uid = _user(app)
    with user_context(uid):
        assembled = export_all_data(uid)
        assembled['_backup'] = {'app': 'arogo', 'version': 1}
        expected = json.dumps(assembled, indent=2, default=str) + '\n'
        assert _streamed(uid) == expected


def test_it_is_identical_for_an_account_with_nothing_in_it(app):
    """Every table empty is the case where a streamed writer most easily emits
    a stray comma or a bare `[ ]`."""
    _c, uid = _user(app, seed=False)
    with user_context(uid):
        assembled = export_all_data(uid)
        assembled['_backup'] = {'app': 'arogo', 'version': 1}
        assert _streamed(uid) == json.dumps(assembled, indent=2, default=str) + '\n'


def test_the_streamed_backup_is_valid_json(app):
    _c, uid = _user(app)
    with user_context(uid):
        parsed = json.loads(_streamed(uid))
    assert parsed['_backup'] == {'app': 'arogo', 'version': 1}
    assert parsed['account']
    assert len(parsed['dose_logs']) == 40


def test_quotes_newlines_and_unicode_survive(app):
    """The values most likely to break a hand-rolled JSON writer."""
    _c, uid = _user(app)
    with user_context(uid):
        parsed = json.loads(_streamed(uid))
    med = parsed['medicines'][0]
    assert med['name'] == 'Metformin "500"'
    assert '\n' in med['notes'] and '\\' in med['notes']
    sym = parsed['symptoms'][0]
    assert sym['name'] == 'Головная боль ☹'
    assert '💊' in sym['notes']


# ── It stays this user's data ───────────────────────────────────────────────

def test_a_backup_contains_only_its_own_users_rows(app):
    _c1, uid1 = _user(app)
    _c2, uid2 = _user(app)
    with user_context(uid1):
        mine = json.loads(_streamed(uid1))
    ids = {d['id'] for d in mine['dose_logs']}
    with user_context(uid2):
        theirs = json.loads(_streamed(uid2))
    assert ids and not (ids & {d['id'] for d in theirs['dose_logs']})
    assert all(d['user_id'] == uid1 for d in mine['dose_logs'])


def test_secrets_are_still_redacted(app):
    """Streaming must not route around _redact — the assembled path applied it
    per row, and so must this one."""
    _c, uid = _user(app)
    with user_context(uid):
        execute("""INSERT INTO user_totp (user_id, secret, recovery, created_at)
                   VALUES (?,?,?,?)""",
                (uid, 'SUPERSECRETTOTPSEED', 'recovery-hashes', now_iso()),
                commit=True)
        body = _streamed(uid)
    assert 'SUPERSECRETTOTPSEED' not in body


# ── It does not hold the whole thing ────────────────────────────────────────

def test_the_generator_yields_before_it_has_finished(app):
    """If the first chunk only arrives once everything is built, nothing has
    been saved — that is the assembled version wearing a generator."""
    _c, uid = _user(app)
    with user_context(uid):
        gen = stream_all_data(uid)
        first = next(gen)
        assert first.strip().startswith('{')
        # And it keeps producing rather than returning one giant string.
        assert sum(1 for _ in gen) > 20


def test_memory_does_not_grow_with_the_number_of_rows(app):
    """The whole reason this exists. Peak memory must be a function of the page
    size, not of how long the person has been using the app — otherwise the
    backup is exactly as fragile as before, just later.

    Measured against the assembled path rather than an absolute number, so the
    test means the same thing on any machine.
    """
    import tracemalloc

    _c, uid = _user(app, seed=False)
    with user_context(uid):
        mid = new_id()
        execute("""INSERT INTO medicines (id,name,active,created_at,user_id)
                   VALUES (?,?,?,?,?)""",
                (mid, 'Metformin', 1, now_iso(), uid), commit=True)
        for i in range(4000):
            execute("""INSERT INTO dose_logs (id,user_id,medicine_id,date_key,
                                              time_key,taken,taken_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (new_id(), uid, mid, '2026-07-01', '09:00', 1, now_iso()))
        execute('SELECT 1', commit=True)

        tracemalloc.start()
        body = json.dumps(export_all_data(uid), indent=2, default=str)
        _cur, peak_assembled = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        size = len(body)
        del body

        tracemalloc.start()
        for _chunk in stream_all_data(uid):
            pass                      # consumed and dropped, as Flask does
        _cur, peak_streamed = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    assert peak_streamed < peak_assembled / 4, (
        f'streaming peaked at {peak_streamed/1024:.0f} KB against '
        f'{peak_assembled/1024:.0f} KB assembled — it is not streaming')
    assert peak_streamed < size, (
        f'peak memory {peak_streamed/1024:.0f} KB exceeds the {size/1024:.0f} KB '
        f'file it produced, so something is still holding the whole thing')


def test_the_route_streams_and_still_downloads(app):
    c, uid = _user(app)
    r = c.get('/api/backup')
    assert r.status_code == 200
    assert 'attachment' in r.headers['Content-Disposition']
    assert 'arogo-backup-' in r.headers['Content-Disposition']
    parsed = json.loads(r.data)
    assert parsed['_backup']['app'] == 'arogo'
    assert len(parsed['dose_logs']) == 40


def test_the_backup_route_needs_a_session(app):
    assert app.test_client().get('/api/backup').status_code == 401


# ── The two paths cover the same tables ─────────────────────────────────────

def test_both_forms_export_exactly_the_same_tables(app):
    """Two functions listing "everything" is how the backup and the restore
    preview come to disagree about what everything means."""
    _c, uid = _user(app)
    with user_context(uid):
        assembled = set(export_all_data(uid))
        streamed = set(json.loads(_streamed(uid)))
    assert streamed - {'_backup'} == assembled
