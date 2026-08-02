"""Server-side i18n: the message catalog + the per-user language preference
that the headless mailer/scheduler read."""
import pytest

import auth as auth_module
import i18n_server
from i18n_server import tr
from app import create_app
from db.core import init_db


@pytest.fixture(scope="module")
def app():
    application = create_app()
    application.config["TESTING"] = True
    init_db()
    return application


@pytest.fixture(autouse=True)
def no_rate_limit():
    auth_module.reset_rate_limiter()
    yield
    auth_module.reset_rate_limiter()


def _reg(app, email):
    c = app.test_client()
    c.post("/auth/register", json={"email": email, "password": "i18n-pw-12345"})
    return c


def _uid_for(email):
    from db.core import execute
    r = execute("SELECT id FROM users WHERE email=?", (email,), fetchone=True)
    return dict(r)["id"] if r else None


def test_tr_english_is_identity_for_missing_lang():
    # English is the fallback and must be byte-identical to the pre-catalog text.
    assert tr('en', 'push.dose_title', med='Metformin') == '💊 Time for Metformin'
    assert tr('en', 'push.snooze_title', med='Aspirin') == '💊 Still due: Aspirin'


def test_tr_hindi_translates_and_fills_placeholders():
    out = tr('hi', 'push.dose_title', med='Metformin')
    assert 'Metformin' in out           # data preserved
    assert out != '💊 Time for Metformin'  # actually translated
    assert any('ऀ' <= c <= 'ॿ' for c in out)  # Devanagari present


def test_tr_never_raises():
    assert tr('hi', 'no.such.key') == 'no.such.key'          # unknown key → key
    assert tr('xx', 'push.water_title')                       # unknown lang → en, no raise
    # Missing format field must not blow up — returns the template unformatted.
    assert '{med}' in tr('en', 'push.dose_title')
    # Unknown lang falls back to English.
    assert tr('fr', 'push.water_title') == tr('en', 'push.water_title')


def test_normalize_lang():
    assert i18n_server.normalize_lang('hi') == 'hi'
    assert i18n_server.normalize_lang('en') == 'en'
    assert i18n_server.normalize_lang(None) == 'en'
    assert i18n_server.normalize_lang('garbage') == 'en'


def test_language_persists_on_profile_and_reads_back(app):
    from db import get_user_language
    email = "lang1@medeasy.test"
    c = _reg(app, email)
    uid = _uid_for(email)

    # Save 'hi' via the profile endpoint, then confirm get_user_language sees it.
    r = c.post('/api/food/profile', json={'language': 'hi'})
    assert r.status_code == 200
    assert r.get_json()['profile'].get('language') == 'hi'
    assert get_user_language(uid) == 'hi'

    # Switching back to English stores 'en'; garbage is ignored (keeps 'en').
    c.post('/api/food/profile', json={'language': 'en'})
    assert get_user_language(uid) == 'en'
    c.post('/api/food/profile', json={'language': 'zz'})
    assert get_user_language(uid) == 'en'


def test_language_absent_defaults_en_and_is_untouched_by_other_saves(app):
    from db import get_user_language
    email = "lang2@medeasy.test"
    c = _reg(app, email)
    uid = _uid_for(email)
    # Never chose a language → defaults to en.
    assert get_user_language(uid) == 'en'
    # A profile save that doesn't mention language must not disturb it.
    c.post('/api/food/profile', json={'language': 'hi'})
    c.post('/api/food/profile', json={'name': 'Asha'})
    assert get_user_language(uid) == 'hi'


def test_get_user_language_defaults_en_for_unknown_user():
    from db import get_user_language
    assert get_user_language('nobody-xyz') == 'en'
