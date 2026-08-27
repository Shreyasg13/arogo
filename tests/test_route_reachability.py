"""Every API endpoint is reachable from the app, or says why not.

This exists because of a bug that has now happened repeatedly: a feature ships
with a working, tested backend and no screen. The tests pass, the API is
correct, and from the user's side nothing was delivered. Two-factor sign-in,
backup status, medicine reconciliation and push-unsubscribe were all in that
state at once — four endpoints, fully tested, that nothing in the UI could
reach.

Tests cannot catch that by testing harder, because the endpoints genuinely
work. What catches it is asking a different question: does anything call this?

The pattern is the same declared-registry one used for search coverage, trash
coverage and export categories. A route is either referenced from the front end
or listed below with a reason. There is no third option, and adding an endpoint
without either fails the build — which is the point, because the failure mode
being prevented is silence.

The reasons below are the real ones, including the unflattering ones. An entry
saying "no in-app caller" is a note that something is unfinished, not a
justification; it just isn't a broken user-facing promise.
"""
import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Referenced from something the browser actually runs. index.html is included
# because a few endpoints are reached by a plain form action or an href.
FRONTEND_FILES = [
    os.path.join(ROOT, 'static', 'js', 'app.js'),
    os.path.join(ROOT, 'static', 'sw.js'),
    os.path.join(ROOT, 'templates', 'index.html'),
]

# Endpoints with no front-end caller, each with the reason. Keep the reason
# specific enough that the next person can tell whether it still holds.
NOT_CALLED_FROM_THE_APP = {
    '/api/digest/unsubscribe/<token>':
        'Opened from a link in a digest email, by someone who may not be signed '
        'in. There is deliberately no in-app button — the whole point is that '
        'it works from the email.',
    '/api/caregiver-digest/unsubscribe/<token>':
        'Same as the digest unsubscribe: reached from the email itself.',

    '/api/dependents/meta':
        'Vocabulary endpoint (relationship and record-kind lists). The picker '
        'currently carries its own copy of the list, so nothing fetches this. '
        'Unfinished rather than wrong — the two could drift.',
    '/api/expenses/meta':
        'Category list for the spending picker, same situation as '
        '/api/dependents/meta: the UI hardcodes its own copy.',

    '/api/hydration/week':
        'A week of water totals. The hydration UI derives its week from the '
        'daily logs it already holds, so this serves API clients only.',
    '/api/stats':
        'Documented summary endpoint for API clients. The dashboard computes '
        'its own figures from the data it already loaded.',
    '/api/reminders/water-status':
        'Documented, tested, and genuinely uncalled — neither the app nor any '
        'other endpoint reads it. Left in place because it is part of the '
        'published API surface, but nothing depends on it.',
}


def _route_decorators():
    """(path, file) for every @bp.route / @app.route in the codebase."""
    out = []
    paths = sorted(glob.glob(os.path.join(ROOT, 'routes', '*.py')))
    paths.append(os.path.join(ROOT, 'app.py'))
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8', errors='replace') as fh:
            src = fh.read()
        for m in re.finditer(r"@\w+\.route\(\s*['\"]([^'\"]+)['\"]", src):
            out.append((m.group(1), os.path.relpath(path, ROOT).replace('\\', '/')))
    return out


_COMMENT_LINE = re.compile(r'\s*(//|\*|/\*|<!--)')


def _frontend_lines():
    """Every front-end line that is not, by itself, a comment.

    Comments do not call anything, and this matters more than it sounds: the
    first version of this guard counted one sentence in a service-worker comment
    that happened to mention /api/2fa as proof that 2FA had a screen — while
    every real caller had been deleted. A check a passing mention satisfies is
    not a check.

    Filtering line by line rather than stripping comments from the whole file is
    deliberate. Stripping /* … */ across a 24,000-line file swallows anything
    between a /* that is really inside a regex literal or a CSS string and the
    next */, which silently hid four endpoints that ARE called. Judging each
    line on its own cannot do that.
    """
    lines = []
    for path in FRONTEND_FILES:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if not _COMMENT_LINE.match(line):
                    lines.append(line)
    return lines


def _frontend_blob():
    return '\n'.join(_frontend_lines())


def _literal_prefix(route):
    """The part of a route before its first <param>, which is what a fetch()
    call in the front end contains literally."""
    return re.split(r'<', route)[0].rstrip('/')


# A handful of routes are too short to search for without matching everything.
_MIN_SEARCHABLE = 6


def test_every_api_route_is_reachable_or_declared():
    blob = _frontend_blob()
    unreachable = []
    for route, where in _route_decorators():
        if not route.startswith('/api'):
            continue
        if route in NOT_CALLED_FROM_THE_APP:
            continue
        prefix = _literal_prefix(route)
        if len(prefix) < _MIN_SEARCHABLE:
            continue
        if prefix not in blob:
            unreachable.append(f'{route}  ({where})')
    assert not unreachable, (
        "these endpoints work and nothing in the app can reach them, so from a "
        "user's side the feature does not exist. Either call it from the front "
        "end, or add it to NOT_CALLED_FROM_THE_APP with the reason:\n  "
        + "\n  ".join(unreachable))


def test_the_exception_list_has_no_stale_entries():
    """An endpoint that gained a caller must leave the list.

    Otherwise the list slowly becomes a place to put things, and stops meaning
    anything — which is how the original bug survived in the first place.
    """
    blob = _frontend_blob()
    declared = {r for r, _ in _route_decorators()}
    stale, gone = [], []
    for route in NOT_CALLED_FROM_THE_APP:
        if route not in declared:
            gone.append(route)
            continue
        if _literal_prefix(route) in blob:
            stale.append(route)
    assert not gone, ("these are listed as unreachable but no longer exist as "
                      "routes: " + ", ".join(gone))
    assert not stale, ("these now have a front-end caller and should be removed "
                       "from NOT_CALLED_FROM_THE_APP: " + ", ".join(stale))


def test_every_exception_gives_a_real_reason():
    for route, reason in NOT_CALLED_FROM_THE_APP.items():
        assert len(reason) > 40, f'{route} needs a real reason, not "{reason}"'


# ── The four that prompted this ─────────────────────────────────────────────
# Named individually so that removing their UI fails with a message that says
# what broke, rather than a generic count.

@pytest.mark.parametrize('endpoint,feature', [
    ('/api/2fa', 'two-factor sign-in'),
    ('/api/backups', 'backup status'),
    ('/api/medicines/changes', 'what changed since the last visit'),
    ('/api/push/unsubscribe', 'turning push reminders off'),
    ('/api/visit-pack', 'the appointment pack'),
])
def test_the_feature_has_a_screen(endpoint, feature):
    assert endpoint in _frontend_blob(), (
        f'{feature} has no way in from the app. The API alone is not the '
        f'feature — {endpoint} is unreachable.')
