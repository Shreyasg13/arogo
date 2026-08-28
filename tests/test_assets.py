"""Static-asset versioning + minification (assets.py + the app.py routes).

Guards two user-facing guarantees:
  1. the service worker's cache name is a content hash, so a deploy always
     invalidates stale code (no hand-bumped version to forget);
  2. minification never drops a translation string or a global function name
     the CSP data-ev dispatcher resolves by string.
"""
import re

import pytest

import assets
from config import Config
from app import create_app


@pytest.fixture(scope="module")
def static_folder():
    return create_app().static_folder


# _deva() counted Devanagari characters in the bundle, back when translation
# packs lived inside app.js. They are separate JSON files now and nothing in the
# bundle is Devanagari, so it counted zero and would have passed forever.


def test_version_is_a_stable_content_hash(static_folder):
    v1 = assets.asset_version(static_folder)
    v2 = assets.asset_version(static_folder)
    assert v1 == v2
    assert re.fullmatch(r'[0-9a-f]{12}', v1)


def test_minify_preserves_globals_translations_and_never_grows(static_folder):
    raw = assets.build_bundle(static_folder, minify=False)
    mn = assets.build_bundle(static_folder, minify=True)

    # Global function names resolved by string by the data-ev dispatcher + the
    # i18n engine must survive (a mangling minifier would break the whole app).
    for token in ('function t(', 'function tformat', 'function markDoseTaken'):
        assert token in mn['app_js'], token

    # Translation LOOKUP KEYS survive minification untouched. This used to check
    # for a Devanagari string, back when the packs were bundled inside app.js.
    # They are fetched from /static/i18n/<code>.json now — and are not minified
    # at all — so the thing at risk here is the other half of the lookup: the
    # English key at the call site. A minifier that rewrote one of these would
    # leave t() searching the pack for a string that no longer exists, and the
    # UI would silently fall back to English.
    for key in ("t('Medicines')", "t('Cancel')", "t('Save')"):
        assert key in mn['app_js'], f'{key} did not survive minification'

    # Minified is never larger than source (equal if the minifiers are absent).
    assert len(mn['app_js']) <= len(raw['app_js'])
    assert len(mn['css']) <= len(raw['css'])


def test_sw_route_stamps_content_version(static_folder):
    app = create_app()
    app.config['TESTING'] = True
    c = app.test_client()

    resp = c.get('/sw.js')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    m = re.search(r"const CACHE_VERSION = 'arogo-([0-9a-f]{12})'", body)
    assert m, "sw.js was not stamped with a content-hash cache version"
    assert m.group(1) == assets.asset_version(static_folder)
    # The SW file must always be revalidated + allowed root scope.
    assert resp.headers.get('Cache-Control') == 'no-cache'
    assert resp.headers.get('Service-Worker-Allowed') == '/'


def test_prod_serves_minified_shell_with_version_etag(static_folder):
    class ProdCfg(Config):
        DEBUG = False
        SECRET_KEY = 'test-prod-secret-not-the-dev-default-000'
        TESTING = True

    app = create_app(ProdCfg)
    c = app.test_client()
    ver = assets.asset_version(static_folder)

    aj = c.get('/static/js/app.js')
    assert aj.status_code == 200
    assert 'javascript' in aj.headers.get('Content-Type', '')
    assert aj.headers.get('ETag') == '"%s"' % ver
    assert 'function t(' in aj.get_data(as_text=True)
    # Repeat load with the same ETag → 304, no body re-sent.
    assert c.get('/static/js/app.js',
                 headers={'If-None-Match': aj.headers['ETag']}).status_code == 304

    css = c.get('/static/css/style.css')
    assert css.status_code == 200
    assert 'text/css' in css.headers.get('Content-Type', '')


def test_dev_leaves_static_to_flask(static_folder):
    # In debug the override is not registered, so edits stay live + debuggable.
    class DevCfg(Config):
        DEBUG = True
        TESTING = True

    app = create_app(DevCfg)
    with app.test_request_context('/static/js/app.js'):
        from flask import request
        assert request.url_rule.endpoint == 'static'
