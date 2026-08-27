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


def test_escape_closes_the_passphrase_dialog():
    """A modal with no way out but the mouse."""
    src = js()
    body = src[src.index('function _passphraseKeys'):]
    assert "'Escape'" in body[:600]
    assert 'cancelPassphrase' in body[:600]


def test_the_passphrase_dialog_traps_and_restores_focus():
    src = js()
    assert '_passphraseReturnFocus' in src, 'focus is never returned to the opener'
    body = src[src.index('function _passphraseKeys'):]
    assert "'Tab'" in body[:900], 'focus can tab out of the open dialog'


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
