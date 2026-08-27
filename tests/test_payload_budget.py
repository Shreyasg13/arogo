"""What the app actually weighs on a phone, measured and held.

This started as a plan to split the monolith, on the basis that app.js is 1.4MB
and style.css is 391KB. Measuring first killed that plan, which is the useful
outcome: the browser never sees those numbers. Minification and gzip are already
in place, so the wire cost is roughly a quarter of the file size, and after the
first visit the service worker serves the shell from cache and the server
answers with 304s.

The remaining levers were all bad trades:

  Splitting app.js by view. The CSP-safe dispatcher resolves handler names as
  strings against the global scope, so chunking is a rewrite of the thing most
  likely to fail silently in production, for a first-load-only win.

  Stripping comments harder than rjsmin does. Worth about 35KB gzipped, and it
  means hand-rolling a comment stripper for JavaScript — the exact task that has
  already gone wrong twice in this repo's own test guards, where a `//` inside a
  regex literal ate half a file. Getting it wrong here breaks production only,
  since minification is off in development.

  Content-hashed asset URLs. Deliberately not done: the service worker's shell
  list and index.html reference the same stable URLs on purpose, and ETag/304 is
  the cost of keeping that simple.

So what this file does instead is hold the line. The numbers below are what the
app weighs today; the budgets sit a little above them. A change that adds a
hundred kilobytes to a first load on mobile data now fails the build and says
so, which is worth more than a risky refactor that saves fifty.
"""
import gzip
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, 'static', 'js', 'app.js')
STYLE = os.path.join(ROOT, 'static', 'css', 'style.css')
INDEX = os.path.join(ROOT, 'templates', 'index.html')
SW = os.path.join(ROOT, 'static', 'sw.js')

KB = 1024

# Budgets in KB, gzipped — what a browser actually pulls down. Headroom is
# deliberately modest: a budget with 50% slack stops being a budget.
BUDGET_APP_JS = 400
BUDGET_STYLE = 62
BUDGET_INDEX = 62
BUDGET_FIRST_LOAD = 520


def _gz_kb(text):
    return len(gzip.compress(text.encode('utf-8'), 6)) / KB


def _read(path):
    return io.open(path, encoding='utf-8').read()


def _minified_js():
    """As production serves it. Falls back to the source when rjsmin is absent,
    which only makes the measured number larger — never smaller, so the budget
    can't be passed by a missing dependency."""
    src = _read(APP_JS)
    try:
        import rjsmin
    except ImportError:
        return src
    try:
        return rjsmin.jsmin(src)
    except Exception:
        return src


def _minified_css():
    src = _read(STYLE)
    try:
        import rcssmin
    except ImportError:
        return src
    try:
        return rcssmin.cssmin(src)
    except Exception:
        return src


def test_app_js_stays_within_budget():
    kb = _gz_kb(_minified_js())
    assert kb <= BUDGET_APP_JS, (
        f'app.js is {kb:.0f}KB gzipped, over the {BUDGET_APP_JS}KB budget. '
        f'This is what someone downloads standing in a pharmacy on mobile data. '
        f'Either trim it, or raise the budget deliberately and say why.')


def test_stylesheet_stays_within_budget():
    kb = _gz_kb(_minified_css())
    assert kb <= BUDGET_STYLE, f'style.css is {kb:.0f}KB gzipped, over {BUDGET_STYLE}KB'


def test_the_html_shell_stays_within_budget():
    """Every view's markup ships in one document. That is a deliberate trade —
    navigation costs nothing afterwards — but it is not free, so it is measured."""
    kb = _gz_kb(_read(INDEX))
    assert kb <= BUDGET_INDEX, f'index.html is {kb:.0f}KB gzipped, over {BUDGET_INDEX}KB'


def test_the_whole_first_load_stays_within_budget():
    total = _gz_kb(_minified_js()) + _gz_kb(_minified_css()) + _gz_kb(_read(INDEX))
    assert total <= BUDGET_FIRST_LOAD, (
        f'a first load is {total:.0f}KB gzipped, over the {BUDGET_FIRST_LOAD}KB '
        f'budget')


def test_the_budgets_are_not_slack():
    """A budget far above the real number is decoration. If the app got smaller,
    this asks for the budget to come down with it."""
    js, css, html = (_gz_kb(_minified_js()), _gz_kb(_minified_css()),
                     _gz_kb(_read(INDEX)))
    assert BUDGET_APP_JS - js <= 80, (
        f'app.js is only {js:.0f}KB but the budget is {BUDGET_APP_JS}KB — lower it')
    assert BUDGET_STYLE - css <= 20, (
        f'style.css is only {css:.0f}KB but the budget is {BUDGET_STYLE}KB')
    assert BUDGET_INDEX - html <= 20, (
        f'index.html is only {html:.0f}KB but the budget is {BUDGET_INDEX}KB')


# ── The things that make those numbers true ─────────────────────────────────

def test_compression_is_still_wired_up():
    """Without gzip the first load is roughly four times bigger. It is done in
    app.py rather than by a dependency so it also covers Flask's own static
    responses."""
    src = _read(os.path.join(ROOT, 'app.py'))
    assert "response.headers['Content-Encoding'] = 'gzip'" in src, (
        'gzip compression has been removed — the first load quadruples')
    assert "Accept-Encoding" in src, 'compression ignores what the client accepts'


def test_minification_never_renames_anything():
    """The CSP-safe dispatcher looks up handler names as strings in the global
    scope, and every translation key is a string literal. A minifier that
    renamed identifiers would break both, silently and in production only."""
    src = _read(os.path.join(ROOT, 'assets.py'))
    assert 'rjsmin' in src and 'rcssmin' in src
    assert 'never rename' in src.lower() or 'no identifier renaming' in src.lower(), (
        'the reason these particular minifiers were chosen is no longer written '
        'down, which is how someone swaps in a smarter one')


def test_minification_failure_serves_working_code():
    """Serving correct code always beats serving small code."""
    src = _read(os.path.join(ROOT, 'assets.py'))
    assert 'except' in src, 'a minifier error would take the whole app down'


def test_the_service_worker_precaches_only_the_shell():
    """A precache list that grows to cover data endpoints turns the install into
    a second, larger download that the user never asked for."""
    src = _read(SW)
    m = re.search(r'const SHELL = \[(.*?)\];', src, re.S)
    assert m, 'the service worker shell list is gone'
    entries = [e.strip().strip("'\",") for e in m.group(1).split('\n') if e.strip().strip(',')]
    entries = [e for e in entries if e and not e.startswith('//')]
    assert len(entries) <= 8, f'the precache list has grown to {len(entries)} entries: {entries}'
    for e in entries:
        assert not e.startswith('/api/'), (
            f'{e} is an API response being precached at install time')


def test_the_asset_urls_stay_stable_for_the_service_worker():
    """Content-hashed URLs would break the shell list, which is why ETag/304 was
    chosen instead. If someone versions the URLs, the SW list has to move too."""
    html = _read(INDEX)
    for asset in ('/static/js/app.js', '/static/css/style.css'):
        assert f'"{asset}"' in html, f'{asset} is no longer referenced plainly'
        assert asset in _read(SW), f'{asset} is not in the service worker shell'
