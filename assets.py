"""
assets.py — Static-asset versioning + optional minification for Arogo.

Two jobs, both aimed at "the user always runs the code we just shipped, and
gets it fast":

1. **Content-hashed version.** `asset_version()` is a short hash of app.js +
   style.css + sw.js. The /sw.js route stamps it into the service worker's
   CACHE_VERSION, so the SW file changes whenever the app does — which is what
   makes the browser notice an update and drop the old cache. Before this the
   version was a hand-bumped string, so forgetting to bump it after a deploy
   left users on stale code (missing logic, old translations) indefinitely.

2. **Minification (production only).** app.js is a large, comment-dense vanilla
   monolith; style.css minifies especially well. rjsmin/rcssmin only strip
   comments and whitespace — they never rename identifiers, so the global
   function names the CSP data-ev dispatcher looks up by string, and every
   translation string literal, are preserved byte-for-byte. If the minifiers
   aren't installed, or minify hiccups, we serve the source unchanged — serving
   correct code always wins over serving small code.

Everything is memoized on the three files' mtimes, so repeated /sw.js and asset
requests don't re-read or re-minify unless something actually changed (a plain
restart-on-deploy on the Pi is enough to pick up new files).
"""
from __future__ import annotations

import hashlib
import os

_CACHE: dict = {}


def _paths(static_folder: str):
    return (
        os.path.join(static_folder, 'js', 'app.js'),
        os.path.join(static_folder, 'css', 'style.css'),
        os.path.join(static_folder, 'sw.js'),
    )


def build_bundle(static_folder: str, minify: bool) -> dict:
    """Return {version, app_js, css, sw_src}, memoized on (mtimes, minify).

    `version` is a 12-char content hash of the three shell files. `app_js`/`css`
    are minified when `minify` is True and the minifiers are available, else the
    raw source. Never raises for a minify problem — it falls back to source."""
    aj, cs, sw = _paths(static_folder)
    try:
        key = (os.path.getmtime(aj), os.path.getmtime(cs), os.path.getmtime(sw))
    except OSError:
        key = None

    # Cache per `minify` value so the version reader (minify=False) and the asset
    # routes (minify=True) don't evict each other on every call.
    cached = _CACHE.get(minify)
    if cached is not None and key is not None and cached.get('key') == key:
        return cached

    with open(aj, encoding='utf-8') as f:
        js_src = f.read()
    with open(cs, encoding='utf-8') as f:
        css_src = f.read()
    with open(sw, encoding='utf-8') as f:
        sw_src = f.read()

    version = hashlib.sha1((js_src + css_src + sw_src).encode('utf-8')).hexdigest()[:12]

    app_js, css = js_src, css_src
    if minify:
        try:
            import rjsmin
            import rcssmin
            app_js = rjsmin.jsmin(js_src)
            css = rcssmin.cssmin(css_src)
        except Exception:
            app_js, css = js_src, css_src   # minifier missing or unhappy → serve source

    data = {'key': key, 'version': version, 'app_js': app_js, 'css': css, 'sw_src': sw_src}
    if key is not None:
        _CACHE[minify] = data
    return data


def asset_version(static_folder: str) -> str:
    """The content-hash version string (used for the SW cache name + ETags)."""
    return build_bundle(static_folder, minify=False)['version']
