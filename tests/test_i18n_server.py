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


# ── A language in SERVER_LANGS must actually be finished ────────────────────
#
# SERVER_LANGS, not the client pack, decides what the scheduler and mailer can
# send. Bengali shipped a complete UI pack and then sent its dose reminders in
# English for months, because nothing connected the two. These tests make the
# tuple mean something: adding a code without finishing MESSAGES fails here.

def _fields(template):
    """The {named} fields in a template. {s} is excluded: it is an English-only
    pluralisation hack ('day{s}') that other languages have no use for, so a
    translation is expected to drop it and str.format ignores the spare."""
    import re
    return {f for f in re.findall(r'\{(\w+)\}', template)} - {'s'}


@pytest.mark.parametrize('code', [c for c in i18n_server.SERVER_LANGS if c != 'en'])
def test_every_offered_server_language_covers_every_message(code):
    missing = sorted(k for k, v in i18n_server.MESSAGES.items() if not v.get(code))
    assert not missing, (
        f'{code} is in SERVER_LANGS but {len(missing)} messages have no '
        f'translation, so those emails and pushes silently fall back to '
        f'English: ' + ', '.join(missing[:8]))


@pytest.mark.parametrize('code', [c for c in i18n_server.SERVER_LANGS if c != 'en'])
def test_translated_templates_keep_the_same_format_fields(code):
    """A dropped {med} sends a reminder that never names the medicine; an
    invented {foo} makes .format() raise, and tr() then sends the raw template
    with braces in it. Both are silent — the push still goes out."""
    bad = []
    for key, entry in i18n_server.MESSAGES.items():
        want, got = _fields(entry['en']), _fields(entry.get(code, ''))
        if want != got:
            bad.append(f'{key}: en={sorted(want)} {code}={sorted(got)}')
    assert not bad, 'format fields differ:\n  ' + '\n  '.join(bad[:8])


@pytest.mark.parametrize('code', [c for c in i18n_server.SERVER_LANGS if c != 'en'])
def test_no_server_translation_is_just_the_english_back(code):
    """An untranslated entry that happens to be copied is indistinguishable
    from a finished one until a user reads it."""
    import re
    same = [k for k, v in i18n_server.MESSAGES.items()
            if v.get(code) == v['en'] and re.search(r'[A-Za-z]{4}', v['en'])]
    assert not same, f'{code} entries still hold the English text: ' + ', '.join(same[:8])


def test_the_client_and_server_language_lists_agree():
    """Two lists in two files, and the failure is invisible: the app switches
    to Marathi and the emails quietly stay English. Read the client's list from
    its source rather than restating it here."""
    import io
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, 'static', 'js', 'app.js'), encoding='utf-8').read()
    block = src[src.index('const SUPPORTED_LANGS = ['):]
    block = block[:block.index('\n];')]
    client = {m.group(1) for line in block.splitlines()
              if not line.strip().startswith('//')
              for m in [re.search(r"code:\s*'([a-z-]+)'", line)] if m}
    server = set(i18n_server.SERVER_LANGS)
    assert client == server, (
        f'the picker offers {sorted(client)} but the server can only write '
        f'{sorted(server)}. A language in only one of them means a user reads a '
        f'translated app and gets English reminders (or the reverse). Finish '
        f'MESSAGES and add the code to SERVER_LANGS, or take it out of both.')


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
    # Clamp to the supported set: case/whitespace tolerated, unsupported → 'en'.
    assert i18n_server.normalize_lang('  HI ') == 'hi'
    assert i18n_server.normalize_lang('ta') == 'en'     # scaffolded, no pack yet → English
    assert i18n_server.normalize_lang('') == 'en'
    assert all(i18n_server.normalize_lang(c) == c for c in i18n_server.SERVER_LANGS)


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


@pytest.mark.parametrize('code', i18n_server.SERVER_LANGS)
def test_every_server_language_survives_a_save_and_a_read(app, code):
    """The choice has to cross two boundaries — the profile write and the
    headless read — and it had a hardcoded ('en','hi') on BOTH. Fixing the
    write alone left every reminder in English, because the read clamped it
    back. Anything in SERVER_LANGS must make the whole round trip.
    """
    from db import get_user_language
    email = f"i18nserver-roundtrip-{code}@medeasy.test"
    c = _reg(app, email)
    uid = _uid_for(email)
    r = c.post('/api/food/profile', json={'language': code})
    assert r.status_code == 200
    assert r.get_json()['profile'].get('language') == code, 'write dropped it'
    assert get_user_language(uid) == code, 'read clamped it back'


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


def test_transactional_emails_localize(monkeypatch):
    import mailer
    cap = {}
    monkeypatch.setattr(mailer, 'send_email',
                        lambda to, subj, text: (cap.update(to=to, subj=subj, text=text), True)[1])

    # Hindi: subject in Devanagari, link preserved.
    mailer.send_verification_email('u@x.test', 'tok123', lang='hi')
    assert 'tok123' in cap['text']
    assert any('ऀ' <= c <= 'ॿ' for c in cap['subj'])

    mailer.send_password_reset_email('u@x.test', 'rtok', lang='hi')
    assert 'rtok' in cap['text']
    assert any('ऀ' <= c <= 'ॿ' for c in cap['text'])

    # English default is byte-identical to the pre-catalog text.
    mailer.send_verification_email('u@x.test', 't', lang='en')
    assert cap['subj'] == 'Verify your Arogo email'
    mailer.send_password_reset_email('u@x.test', 't', lang='en')
    assert cap['subj'] == 'Reset your Arogo password'
    assert cap['text'].startswith('Someone requested a password reset')


def test_weekly_digest_prose_and_email_localize(app, monkeypatch):
    from db.insights import generate_weekly_digest
    from db.core import user_context
    email = "digesthi@medeasy.test"
    c = _reg(app, email)
    uid = _uid_for(email)

    with user_context(uid):
        d_hi = generate_weekly_digest('hi')
        d_en = generate_weekly_digest('en')
    # An empty week → the welcoming headline, localized.
    assert any('ऀ' <= ch <= 'ॿ' for ch in d_hi['headline'])
    assert d_en['headline'] == 'Nothing logged yet — start tracking and your progress will show up here.'

    import mailer
    cap = {}
    monkeypatch.setattr(mailer, 'send_email',
                        lambda to, subj, text: (cap.update(subj=subj, text=text), True)[1])
    # Hindi scaffolding.
    mailer.send_weekly_digest_email('x@y.test', 'Asha', d_hi, 'http://u/unsub', lang='hi')
    assert any('ऀ' <= ch <= 'ॿ' for ch in cap['subj'])
    assert 'आपका हफ़्ता' in cap['text']
    # English default byte-identical.
    mailer.send_weekly_digest_email('x@y.test', 'Asha', d_en, 'http://u/unsub', lang='en')
    assert cap['subj'].startswith('Your Arogo week —')
    assert 'Your week:' in cap['text']


def test_scheduler_push_localizes_to_hindi(app, monkeypatch):
    """End-to-end: a Hindi user's dose-snooze push comes out in Devanagari,
    while the default (English) path is unchanged (asserted elsewhere)."""
    import scheduler
    import push
    from db.core import execute

    email = "hindipush@medeasy.test"
    c = _reg(app, email)
    uid = _uid_for(email)
    c.post('/api/food/profile', json={'language': 'hi'})   # choose Hindi

    m = c.post("/api/medicines", json={
        "name": "Amlodipine", "dosage": "5", "unit": "mg",
        "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id,endpoint,user_id,sub_json,created_at) "
            "VALUES (?,?,?,?,?)", ("s-hi", "https://push.test/hi", uid, "{}", "2026-01-01"),
            commit=True)
    c.post(f"/api/medicines/{m['id']}/snooze", json={"time": "09:00"})
    execute("UPDATE dose_snoozes SET snooze_until=? WHERE med_id=? AND user_id=?",
            ("2000-01-01T00:00:00", m["id"], uid), commit=True)

    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user",
                        lambda u, t, b, *a, **k: (sent.append((u, t)) or 1))
    scheduler._push_reminders()

    mine = [t for (u, t) in sent if u == uid]
    assert mine, "no push captured for the Hindi user"
    assert any("अब भी देय" in t for t in mine)     # Hindi snooze title
    assert not any("Still due" in t for t in mine)  # never the English string


# The addresses are spelled out rather than built by interpolating the language
# code onto a shared suffix. The literal tail of such an f-string is an address
# test_push.py already owns, and the conventions guard rightly calls that a
# parallel-run flake. (It scans raw source, so do not write the offending
# address here either — this comment used to, and failed the same check.)
@pytest.mark.parametrize('code,expect,email', [
    ('bn', 'এখনও বাকি', 'i18nserver-bn-reminder@medeasy.test'),
    ('mr', 'अजूनही बाकी', 'i18nserver-mr-reminder@medeasy.test'),
])
def test_scheduler_push_localizes_to_the_newer_languages(app, monkeypatch,
                                                         code, expect, email):
    """The same end-to-end path as the Hindi test, for the two languages that
    had a complete UI pack and English reminders. A catalog entry that exists
    is not the same as one the scheduler actually reaches."""
    import scheduler
    import push
    from db.core import execute

    c = _reg(app, email)
    uid = _uid_for(email)
    c.post('/api/food/profile', json={'language': code})

    m = c.post("/api/medicines", json={
        "name": "Amlodipine", "dosage": "5", "unit": "mg",
        "frequency": "once_daily", "times": ["09:00"]}).get_json()["medicine"]
    execute("DELETE FROM push_subscriptions WHERE user_id=?", (uid,), commit=True)
    execute("INSERT INTO push_subscriptions (id,endpoint,user_id,sub_json,created_at) "
            "VALUES (?,?,?,?,?)", (f"s-{code}", f"https://push.test/{code}", uid,
                                   "{}", "2026-01-01"), commit=True)
    c.post(f"/api/medicines/{m['id']}/snooze", json={"time": "09:00"})
    execute("UPDATE dose_snoozes SET snooze_until=? WHERE med_id=? AND user_id=?",
            ("2000-01-01T00:00:00", m["id"], uid), commit=True)

    sent = []
    monkeypatch.setattr(push, "PUSH_AVAILABLE", True)
    monkeypatch.setattr(push, "push_to_user",
                        lambda u, t, b, *a, **k: (sent.append((u, t)) or 1))
    scheduler._push_reminders()

    mine = [t for (u, t) in sent if u == uid]
    assert mine, f"no push captured for the {code} user"
    assert any(expect in t for t in mine), f'{code} push was {mine}'
    assert not any("Still due" in t for t in mine)
    # The medicine name is the user's own text and must survive translation.
    assert any("Amlodipine" in t for t in mine)


def test_transactional_emails_localize_for_bengali_and_marathi(monkeypatch):
    import mailer
    cap = {}
    monkeypatch.setattr(mailer, 'send_email',
                        lambda to, subj, text: (cap.update(subj=subj, text=text), True)[1])
    for code, sample in (('bn', 'যাচাই'), ('mr', 'पडताळा')):
        mailer.send_verification_email('u@x.test', 'tok123', lang=code)
        assert sample in cap['subj'], f'{code} subject was {cap["subj"]!r}'
        assert 'tok123' in cap['text'], f'{code} lost the token'
