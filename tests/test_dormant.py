"""
tests/test_dormant.py — capability the data earned, still switched off.

The risk here is not a wrong number, it is a nag. A panel that tells people to
do things they never asked to do is worse than no panel, so most of these tests
are about what must NOT appear: nothing before the data earns it, nothing
already switched on, nothing after it has been waved away, and nothing about
another user's account.
"""
import uuid

import pytest

import auth as auth_module
from app import create_app
from db.core import execute, init_db, new_id, now_iso, user_context
from db.dormant import CHECKS, dismiss, report, restore

PW = 'Dormant2026!'


@pytest.fixture(scope='module')
def app():
    a = create_app(); a.config['TESTING'] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _user(app):
    email = f'dormant-{uuid.uuid4().hex[:10]}@x.test'
    c = app.test_client()
    c.post('/auth/register', json={'email': email, 'password': PW})
    uid = dict(execute('SELECT id FROM users WHERE email=?', (email,),
                       fetchone=True))['id']
    return c, uid


def _vitals(uid, n, vtype='blood_pressure'):
    for i in range(n):
        execute("""INSERT INTO vitals (id,date_key,type,value1,unit,logged_at,user_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (new_id(), f'2026-08-{i % 28 + 1:02d}', vtype, 120 + i, 'mmHg',
                 now_iso(), uid), commit=True)


def _target(uid, vtype='blood_pressure'):
    execute("""INSERT INTO vital_targets (id,vtype,target_min,target_max,updated_at,user_id)
               VALUES (?,?,?,?,?,?)""",
            (new_id(), vtype, 90, 130, now_iso(), uid), commit=True)


def _keys(rep):
    return {i['key'] for i in rep['items']}


# ── The registry is complete ────────────────────────────────────────────────

def test_every_check_declares_everything_it_needs():
    for c in CHECKS:
        for field in ('key', 'name', 'earned', 'on', 'unlocks', 'step', 'view'):
            assert field in c, f'{c.get("key", c)} has no {field}'
        assert callable(c['earned']) and callable(c['on']), c['key']


def test_no_two_checks_share_a_key():
    keys = [c['key'] for c in CHECKS]
    assert len(keys) == len(set(keys)), keys


@pytest.mark.parametrize('c', CHECKS, ids=lambda c: c['key'])
def test_every_check_says_what_it_would_unlock_in_the_users_own_terms(c):
    """"Set up targets" is a chore. "Nothing can tell you whether your 25
    readings are in range" is a reason. The difference is the whole feature."""
    assert len(c['unlocks']) > 70, (
        f'{c["key"]}: the unlocks line does not say what the person actually '
        f'gains — got {c["unlocks"]!r}')
    assert '%1' in c['unlocks'], (
        f'{c["key"]}: says nothing about THIS account. A sentence with none of '
        f'their own numbers in it is a brochure, not a suggestion.')
    assert len(c['step']) < 40, f'{c["key"]}: the step should be one action'


@pytest.mark.parametrize('c', CHECKS, ids=lambda c: c['key'])
def test_every_check_points_at_a_real_view(c):
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = io.open(os.path.join(root, 'templates', 'index.html'),
                   encoding='utf-8').read()
    assert f'id="view-{c["view"]}"' in html, (
        f'{c["key"]} sends the user to view-{c["view"]}, which does not exist')


# ── Nothing appears before the data earns it ────────────────────────────────

def test_a_brand_new_account_is_offered_nothing(app):
    """The strongest rule: someone who has logged nothing is asked for nothing.
    A fresh account seeing six suggestions is a chore list, not help."""
    _c, uid = _user(app)
    with user_context(uid):
        assert report()['items'] == []


def test_a_few_readings_are_not_enough_to_ask_about_targets(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 3)
        assert 'vital_targets' not in _keys(report())


def test_enough_readings_earns_the_suggestion(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 6)
        rep = report()
        assert 'vital_targets' in _keys(rep)
        item = next(i for i in rep['items'] if i['key'] == 'vital_targets')
        assert item['detail']['count'] == 6
        assert item['detail']['vital'] == 'blood_pressure'


def test_it_disappears_once_switched_on(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 6)
        assert 'vital_targets' in _keys(report())
        _target(uid)
        assert 'vital_targets' not in _keys(report())


def test_readings_of_a_type_that_cannot_carry_a_target_do_not_count(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 8, vtype='something_else')
        assert 'vital_targets' not in _keys(report())


# ── It stays this user's account ────────────────────────────────────────────

def test_one_users_data_never_earns_another_users_suggestion(app):
    _c1, uid1 = _user(app)
    _c2, uid2 = _user(app)
    with user_context(uid1):
        _vitals(uid1, 9)
        assert 'vital_targets' in _keys(report())
    with user_context(uid2):
        assert 'vital_targets' not in _keys(report())


def test_a_dismissal_is_not_shared_between_users(app):
    """It cannot live in app_config, which is global — one person waving a
    suggestion away must not silence it for everyone on the server."""
    _c1, uid1 = _user(app)
    _c2, uid2 = _user(app)
    for uid in (uid1, uid2):
        with user_context(uid):
            _vitals(uid, 7)
    with user_context(uid1):
        dismiss('vital_targets')
        assert 'vital_targets' not in _keys(report())
    with user_context(uid2):
        assert 'vital_targets' in _keys(report())


# ── Dismissal ───────────────────────────────────────────────────────────────

def test_dismissing_hides_it_and_says_how_many_are_hidden(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 7)
        dismiss('vital_targets')
        rep = report()
        assert 'vital_targets' not in _keys(rep)
        assert rep['dismissed_count'] == 1


def test_a_dismissal_can_be_undone(app):
    """A one-way "never show me this" with no way back is a setting the user
    cannot find again."""
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 7)
        dismiss('vital_targets')
        assert 'vital_targets' not in _keys(report())
        restore('vital_targets')
        assert 'vital_targets' in _keys(report())


def test_dismissed_items_can_be_listed_deliberately(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 7)
        dismiss('vital_targets')
        rep = report(include_dismissed=True)
        item = next(i for i in rep['items'] if i['key'] == 'vital_targets')
        assert item['dismissed'] is True


def test_dismissing_something_unknown_is_refused(app):
    _c, uid = _user(app)
    with user_context(uid):
        assert dismiss('not-a-real-suggestion') is False


def test_dismissing_one_does_not_dismiss_the_others(app):
    _c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 7)
        execute("""INSERT INTO medicines (id,name,active,times,created_at,user_id)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), 'Metformin', 1, '["09:00"]', now_iso(), uid), commit=True)
        dismiss('vital_targets')
        keys = _keys(report())
        assert 'vital_targets' not in keys
        assert 'push' in keys, 'dismissing one suggestion silenced another'


# ── It survives a bad check ─────────────────────────────────────────────────

def test_one_broken_check_does_not_take_the_panel_down(app):
    _c, uid = _user(app)
    original = CHECKS[0]['earned']

    def boom():
        raise RuntimeError('no such column')

    CHECKS[0]['earned'] = boom
    try:
        with user_context(uid):
            _vitals(uid, 7)
            report()          # must not raise
    finally:
        CHECKS[0]['earned'] = original


# ── The routes ──────────────────────────────────────────────────────────────

def test_dormant_needs_a_session(app):
    assert app.test_client().get('/api/dormant').status_code == 401


def test_dormant_route_reports_and_dismisses(app):
    c, uid = _user(app)
    with user_context(uid):
        _vitals(uid, 8)
    body = c.get('/api/dormant').get_json()
    assert 'vital_targets' in {i['key'] for i in body['items']}

    assert c.post('/api/dormant/vital_targets/dismiss').status_code == 200
    body = c.get('/api/dormant').get_json()
    assert 'vital_targets' not in {i['key'] for i in body['items']}

    assert c.delete('/api/dormant/vital_targets/dismiss').status_code == 200
    body = c.get('/api/dormant').get_json()
    assert 'vital_targets' in {i['key'] for i in body['items']}


def test_dismissing_an_unknown_key_is_a_400(app):
    c, _uid = _user(app)
    assert c.post('/api/dormant/nonsense/dismiss').status_code == 400
