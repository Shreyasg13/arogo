"""
tests/test_nav_prefs.py — hiding sections from the menu, safely.

Arogo shows all fifty-five sections to everyone. Letting people hide the ones
they do not use is obviously right and obviously dangerous: this codebase has a
whole test file about features that shipped with no route to them, and hiding
is the same failure with a friendlier name.

Two guarantees, both tested rather than promised:

  Essential sections cannot be hidden, whatever the client sends.
  Nothing hidden becomes unreachable — every section stays in global search.
"""
import io
import os
import re
import uuid

import pytest

import auth as auth_module
from app import create_app
from db.core import execute, init_db, new_id, now_iso, user_context
from db.nav_prefs import (BACKED_BY, ESSENTIAL, hidden, report, set_hidden,
                          unused)

PW = 'NavPrefs2026!'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope='module')
def app():
    a = create_app(); a.config['TESTING'] = True; init_db(); return a


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter(); yield; auth_module.reset_rate_limiter()


def _user(app):
    email = f'nav-{uuid.uuid4().hex[:10]}@x.test'
    c = app.test_client()
    c.post('/auth/register', json={'email': email, 'password': PW})
    uid = dict(execute('SELECT id FROM users WHERE email=?', (email,),
                       fetchone=True))['id']
    return c, uid


def _html():
    return io.open(os.path.join(ROOT, 'templates', 'index.html'),
                   encoding='utf-8').read()


def _js():
    return io.open(os.path.join(ROOT, 'static', 'js', 'app.js'),
                   encoding='utf-8').read()


def _sidebar_views():
    return set(re.findall(r'data-view="([a-z0-9-]+)"', _html()))


def _searchable_views():
    js = _js()
    block = js[js.index('const NAV_TARGETS = ['):]
    block = block[:block.index('\n];')]
    return set(re.findall(r"v:'([a-z0-9-]+)'", block))


# ── Nothing hidden can become unreachable ───────────────────────────────────

def test_every_section_in_the_menu_is_also_findable_by_search():
    """The escape hatch the whole feature rests on. If a section is only
    reachable from the menu, hiding it removes it from the app."""
    missing = sorted(_sidebar_views() - _searchable_views())
    assert not missing, (
        f'{len(missing)} sections are in the menu but not in NAV_TARGETS, so '
        f'hiding them would strand them: {missing}')


def test_every_hideable_section_is_searchable():
    """Stated separately from the sidebar check, because the set a user may
    hide is the set that must survive being hidden."""
    hideable = _sidebar_views() - set(ESSENTIAL)
    stranded = sorted(hideable - _searchable_views())
    assert not stranded, f'hiding these would make them unreachable: {stranded}'


def test_the_search_index_is_not_empty():
    """A guard on the guard: if NAV_TARGETS could not be parsed, the two tests
    above would pass vacuously and the safety net would be imaginary."""
    assert len(_searchable_views()) > 40


# ── Essential sections stay ─────────────────────────────────────────────────

def test_the_essential_list_matches_the_template():
    """A section essential in Python and hideable in the template is how
    someone loses their medicines list."""
    html = _html()
    marked = set(re.findall(r'data-view="([a-z0-9-]+)"[^>]*data-essential', html))
    marked |= set(re.findall(r'data-essential[^>]*data-view="([a-z0-9-]+)"', html))
    assert marked == set(ESSENTIAL), (
        f'template marks {sorted(marked)} essential, nav_prefs says '
        f'{sorted(ESSENTIAL)}')


@pytest.mark.parametrize('view', ESSENTIAL)
def test_an_essential_section_cannot_be_hidden(app, view):
    c, uid = _user(app)
    with user_context(uid):
        set_hidden([view, 'quit'])
        assert view not in hidden()
        assert 'quit' in hidden()


def test_hiding_everything_still_leaves_the_essentials(app):
    """The worst case a user can create for themselves in one action."""
    _c, uid = _user(app)
    with user_context(uid):
        set_hidden(sorted(_sidebar_views()))
        left = _sidebar_views() - hidden()
        assert set(ESSENTIAL) <= left, f'only {sorted(left)} would remain'


def test_a_section_that_becomes_essential_later_is_not_still_hidden(app):
    """The stored string outlives the code. Someone hides 'family' today; if it
    becomes essential tomorrow, yesterday's string must not keep it hidden."""
    _c, uid = _user(app)
    with user_context(uid):
        # Write straight past set_hidden, as an older version would have.
        execute("UPDATE user_profile SET nav_hidden=? WHERE user_id=?",
                ('quit,dashboard,medicines', uid), commit=True)
        assert hidden() == {'quit'}


# ── Storing the choice ──────────────────────────────────────────────────────

def test_hidden_starts_empty_so_nothing_changes_for_existing_accounts(app):
    _c, uid = _user(app)
    with user_context(uid):
        assert hidden() == set()


def test_a_choice_round_trips(app):
    _c, uid = _user(app)
    with user_context(uid):
        set_hidden(['quit', 'fasting', 'claims'])
        assert hidden() == {'quit', 'fasting', 'claims'}
        set_hidden(['quit'])
        assert hidden() == {'quit'}
        set_hidden([])
        assert hidden() == set()


def test_blank_and_duplicate_entries_are_ignored(app):
    _c, uid = _user(app)
    with user_context(uid):
        set_hidden(['quit', '  quit ', '', '   ', 'fasting'])
        assert hidden() == {'quit', 'fasting'}


def test_one_users_menu_is_not_another_users(app):
    _c1, uid1 = _user(app)
    _c2, uid2 = _user(app)
    with user_context(uid1):
        set_hidden(['quit'])
    with user_context(uid2):
        assert hidden() == set()


# ── "Hide what I don't use" ─────────────────────────────────────────────────

def test_every_backed_by_table_exists():
    """A section mapped to a table that does not exist would be reported as
    unused forever, because the query fails every time."""
    from db.core import table_columns
    for view, tables in BACKED_BY.items():
        for t in tables:
            assert table_columns(t), f'{view} is backed by {t}, which does not exist'


def test_every_backed_by_key_is_actually_in_the_menu():
    """Suggesting you hide a section that was never in the menu is noise at
    best — the tick does nothing. Four keys were wrong this way (falls, rehab,
    hearing, donations have views but are reached from elsewhere)."""
    stray = sorted(set(BACKED_BY) - _sidebar_views())
    assert not stray, f'not in the sidebar, so hiding them means nothing: {stray}'


def test_no_essential_section_is_ever_suggested_for_hiding():
    assert not (set(BACKED_BY) & set(ESSENTIAL))


def test_an_untouched_section_is_reported_as_unused(app):
    _c, uid = _user(app)
    with user_context(uid):
        assert 'quit' in unused()


def test_a_section_with_one_row_is_no_longer_unused(app):
    _c, uid = _user(app)
    with user_context(uid):
        assert 'claims' in unused()
        execute("""INSERT INTO claims (id,insurer,amount,date_submitted,
                                      created_at,user_id)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), 'Star Health', 1200, '2026-08-01', now_iso(), uid),
                commit=True)
        assert 'claims' not in unused()


def test_unused_is_a_suggestion_and_hides_nothing_by_itself(app):
    """The app offering to tidy the menu is not the app deciding what someone
    needs. Someone who has not logged a pregnancy may be about to."""
    _c, uid = _user(app)
    with user_context(uid):
        assert unused()
        assert hidden() == set()


# ── The routes ──────────────────────────────────────────────────────────────

def test_nav_prefs_needs_a_session(app):
    assert app.test_client().get('/api/nav-prefs').status_code == 401


def test_the_route_reports_and_saves(app):
    c, uid = _user(app)
    body = c.get('/api/nav-prefs').get_json()
    assert body['hidden'] == []
    assert set(body['essential']) == set(ESSENTIAL)
    assert 'quit' in body['unused']

    r = c.put('/api/nav-prefs', json={'hidden': ['quit', 'fasting']})
    assert r.status_code == 200
    assert set(r.get_json()['hidden']) == {'quit', 'fasting'}
    assert set(c.get('/api/nav-prefs').get_json()['hidden']) == {'quit', 'fasting'}


def test_the_route_refuses_to_hide_an_essential_section(app):
    c, _uid = _user(app)
    r = c.put('/api/nav-prefs', json={'hidden': ['dashboard', 'medicines', 'quit']})
    assert r.status_code == 200
    assert r.get_json()['hidden'] == ['quit']


def test_report_shape(app):
    _c, uid = _user(app)
    with user_context(uid):
        r = report()
    assert set(r) == {'hidden', 'essential', 'unused'}
