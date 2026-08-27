"""Accessibility on the pages added in the recent rounds.

Several pages went in fast and none had an accessibility pass. That is the kind
of rot that is hard to reverse: by the time anyone notices, the markup is spread
across a 24,000-line file and the cost of fixing it has multiplied.

These are static checks against the template, not a substitute for using the app
with a screen reader. They cover the three failures that are both mechanical to
detect and genuinely disabling:

  A panel that fills in after a fetch, with no live region — a sighted user sees
  "Loading…" become a backup status; a screen-reader user hears nothing at all
  and has no reason to go back and look.

  A form control with no accessible name, announced as "edit text, blank".

  A dialog with no dialog semantics and no focus handling, which a keyboard user
  can tab straight out of while it is still on screen.
"""
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'templates', 'index.html')
APP_JS = os.path.join(ROOT, 'static', 'js', 'app.js')


def html():
    return io.open(INDEX, encoding='utf-8').read()


def js():
    return io.open(APP_JS, encoding='utf-8').read()


# ── Panels that fill in asynchronously ──────────────────────────────────────

# Every container written to by a fetch on the newer pages. A change here is a
# deliberate one: adding a panel without a live region should require saying so.
LIVE_REGIONS = [
    ('twofa-panel', 'two-factor status and enrolment'),
    ('backup-status', 'whether the backup is healthy'),
    ('push-control', 'whether push reminders are on'),
    ('visitpack-body', 'the whole appointment pack'),
    ('trash-list', 'what is in the trash'),
    ('storage-report', 'how much disk is left'),
    ('med-changes-card', 'what changed since the last visit'),
]


@pytest.mark.parametrize('element_id,what', LIVE_REGIONS)
def test_an_async_panel_announces_itself(element_id, what):
    raw = html()
    m = re.search(r'<[^>]*id="' + re.escape(element_id) + r'"[^>]*>', raw)
    assert m, f'#{element_id} is gone from the template'
    assert 'aria-live' in m.group(0), (
        f'#{element_id} is filled in after a fetch and never announces {what} — '
        f'add aria-live="polite"')


# ── Controls have names ─────────────────────────────────────────────────────

def _labelled_ids(raw):
    return set(re.findall(r'<label[^>]*\bfor="([^"]+)"', raw))


# Inputs added on the newer pages. A control here without a name is announced
# as "edit text, blank", which on a passphrase field is the difference between
# usable and not.
NAMED_CONTROLS = [
    'trash-search', 'export-passphrase', 'passphrase-input', 'vp-appointment',
]


@pytest.mark.parametrize('element_id', NAMED_CONTROLS)
def test_a_control_has_an_accessible_name(element_id):
    raw = html()
    m = re.search(r'<(?:input|select|textarea)[^>]*id="' + re.escape(element_id)
                  + r'"[^>]*>', raw)
    assert m, f'#{element_id} is gone from the template'
    tag = m.group(0)
    has_name = ('aria-label' in tag or 'aria-labelledby' in tag
                or element_id in _labelled_ids(raw))
    assert has_name, (
        f'#{element_id} has no accessible name — give it an aria-label or a '
        f'<label for="{element_id}">')


# ── The passphrase dialog ───────────────────────────────────────────────────

def test_the_passphrase_dialog_is_a_dialog():
    raw = html()
    m = re.search(r'<div[^>]*id="passphrase-overlay"[^>]*>', raw)
    assert m, 'the passphrase dialog is gone'
    tag = m.group(0)
    assert 'role="dialog"' in tag
    assert 'aria-modal="true"' in tag
    assert 'aria-labelledby=' in tag, 'the dialog has no accessible name'


def test_escape_closes_any_open_dialog():
    """A modal with no way out but the mouse.

    This started as a bespoke handler on the one dialog that had it. It is now
    shared by all 25, which is why the test moved with it — pinning the private
    helper would have failed the moment the behaviour got better.
    """
    src = js()
    assert "e.key !== 'Escape'" in src or "'Escape'" in src
    body = src[src.index('function _closeVisibleModal'):]
    # Escape clicks the dialog's own ×, so per-modal close logic still runs —
    # several of them resolve a promise or clear a draft on the way out.
    assert '.modal-close' in body[:400]


def test_an_open_dialog_traps_and_restores_focus():
    src = js()
    assert '_modalOpener' in src, 'focus is never returned to whatever opened it'
    body = src[src.index('function _watchModalVisibility'):]
    assert 'MutationObserver' in body[:900], (
        'nothing notices a dialog opening, so focus never moves into it')
    assert '_focusIntoModal' in body[:1400]


def test_the_focus_trap_covers_every_dialog_not_just_one():
    """Fifty functions open modals by setting style.display. Watching for that
    is the only way this cannot rot the next time someone adds one."""
    src = js()
    body = src[src.index('function _watchModalVisibility'):]
    assert "querySelectorAll('.modal-overlay')" in body[:400]
    assert "attributeFilter: ['style']" in body[:1600]


def test_cancelling_is_distinguishable_from_an_empty_passphrase():
    """An empty passphrase is a thing someone can type; cancelling is not, and
    conflating them would run a decrypt nobody asked for."""
    src = js()
    body = src[src.index('function cancelPassphrase'):]
    assert 'resolve(null)' in body[:400] or '(null)' in body[:400]


# ── No new inline handlers ──────────────────────────────────────────────────

def test_the_new_markup_uses_delegated_events():
    """Inline on*= handlers break the Content-Security-Policy the app runs
    under, so they fail closed rather than loudly."""
    raw = html()
    start = raw.find('id="view-visitpack"')
    assert start > 0
    section = raw[start:start + 2000]
    assert not re.search(r'\son(click|change|input|keydown)=', section)


# ── Every dialog in the app, not just the new ones ──────────────────────────
# The app had 25 modal overlays and 2 with dialog semantics. A dialog without
# them is announced as a generic group: a screen-reader user is not told a
# dialog opened, is not told its name, and is not kept inside it.

def _overlays():
    return re.findall(r'<div class="modal-overlay"[^>]*>', html())


def test_every_modal_is_announced_as_a_dialog():
    missing = [o for o in _overlays() if 'role="dialog"' not in o]
    assert not missing, (
        f'{len(missing)} modal overlays have no dialog role — a screen reader '
        f'announces them as an ordinary group: ' + '; '.join(o[:90] for o in missing[:4]))


def test_every_modal_is_marked_modal():
    """Without aria-modal, assistive technology keeps offering the page behind
    the dialog as if it were still available."""
    missing = [o for o in _overlays() if 'aria-modal="true"' not in o]
    assert not missing, f'{len(missing)} overlays are not marked aria-modal'


def test_every_modal_has_a_name():
    missing = [o for o in _overlays()
               if 'aria-labelledby' not in o and 'aria-label=' not in o]
    assert not missing, (
        f'{len(missing)} dialogs open with no name, so all a screen reader can '
        f'say is "dialog": ' + '; '.join(o[:90] for o in missing[:4]))


def test_every_dialog_label_points_at_something_real():
    """A dangling aria-labelledby is worse than none: the browser falls back to
    nothing and the markup looks correct."""
    raw = html()
    ids = set(re.findall(r'\sid="([^"]+)"', raw))
    dangling = []
    for o in _overlays():
        m = re.search(r'aria-labelledby="([^"]+)"', o)
        if m and m.group(1) not in ids:
            dangling.append(m.group(1))
    assert not dangling, 'aria-labelledby points at missing ids: ' + ', '.join(dangling)


def test_every_dialog_can_be_closed_without_a_mouse():
    """Escape works by clicking the dialog's own close button, so a dialog
    without one cannot be dismissed from the keyboard at all."""
    raw = html()
    unclosable = []
    for m in re.finditer(r'<div class="modal-overlay"[^>]*id="([^"]+)"', raw):
        nxt = raw.find('<div class="modal-overlay"', m.end())
        region = raw[m.end():nxt if nxt != -1 else len(raw)]
        if 'modal-close' not in region:
            unclosable.append(m.group(1))
    assert not unclosable, (
        'these dialogs have no close button, so Escape has nothing to click: '
        + ', '.join(unclosable))


# ── Controls that announce as nothing ───────────────────────────────────────

def _buttons():
    raw = html()
    out = []
    for m in re.finditer(r'<button\b', raw):
        end = raw.find('</button>', m.start())
        if end == -1:
            continue
        full = raw[m.start():end + 9]
        attrs = full[:full.find('>') + 1]
        inner = full[full.find('>') + 1:-9]
        text = re.sub(r'<[^>]+>', '', re.sub(r'<svg.*?</svg>', '', inner, flags=re.S))
        out.append((attrs, re.sub(r'[^\w]', '', text)))
    return out


def test_no_button_announces_as_nothing():
    """Every icon in this app is marked aria-hidden (it sits beside its own
    label), so a button whose only content is an SVG has no name at all unless
    one is given. 30 of them were in that state.

    A `title` counts: the runtime pass copies it to aria-label, because a title
    alone is not reliably announced.
    """
    nameless = [a for a, text in _buttons()
                if not text and 'aria-label' not in a
                and 'aria-labelledby' not in a and 'title=' not in a]
    assert not nameless, (
        f'{len(nameless)} buttons would be announced as just "button": '
        + '; '.join(a[:100] for a in nameless[:5]))


def test_the_runtime_pass_names_title_only_buttons():
    src = js()
    body = src[src.index('root.querySelectorAll(\'button:not([data-a11y-name])\')'):]
    assert "getAttribute('title')" in body[:700]
    assert "setAttribute('aria-label'" in body[:700]
    # It must not overwrite a real label, and must skip buttons with visible text.
    assert 'textContent' in body[:700]


def test_the_skip_link_still_points_at_the_main_landmark():
    raw = html()
    m = re.search(r'<a href="#([^"]+)" class="skip-link"', raw)
    assert m, 'the skip-to-content link is gone'
    assert f'id="{m.group(1)}"' in raw, 'the skip link points at nothing'


def test_focus_only_ever_targets_a_visible_control():
    """The bug this pins: several dialogs hide a file input behind a styled
    label, and .focus() on a display:none element does nothing — silently. The
    first version picked exactly such an input and left focus on the body,
    which looks identical to the trap not running at all."""
    src = js()
    body = src[src.index('function _visibleFocusable'):]
    assert 'offsetParent !== null' in body[:500], (
        'focus candidates are not filtered to visible elements')
    focuser = src[src.index('function _focusIntoModal'):]
    assert '_visibleFocusable(' in focuser[:400], (
        '_focusIntoModal queries the DOM directly again instead of reusing the '
        'visibility filter, which is how the two drifted apart the first time')


def test_the_tab_trap_uses_the_same_visibility_filter():
    src = js()
    handler = src[src.index("if (e.key !== 'Escape' && e.key !== 'Tab')"):]
    assert '_visibleFocusable(' in handler[:900], (
        'the Tab trap can land focus on a hidden control')
