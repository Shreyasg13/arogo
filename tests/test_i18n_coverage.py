"""Hindi coverage: measured, floored, and required outright on newer pages.

The app offers Hindi, and several pages built in the last few rounds shipped
ignoring it entirely. That is a worse failure than an untranslated app: the user
already told it which language they read, and it answered in English anyway on
exactly the screens they had not seen before.

Complete coverage is not claimed and is not asserted, because it would be a lie
— the honest number is measured here and printed in the failure message. What IS
asserted is that it cannot go backwards, and that the pages listed in
REQUIRE_FULL_COVERAGE are complete. A page joins that list when it is finished,
and once on it, shipping an untranslated string there fails the build.

Two traps this encodes, both of which were live while writing it:

  Keys are packed several to a line in the pack, so a line-anchored regex finds
  almost none of them and reports a gap ten times bigger than the real one.

  data-i18n attributes are read with getAttribute(), which returns the DECODED
  value. The key is "Sign-in & activity", never "Sign-in &amp; activity", and a
  checker that reads the raw HTML compares the wrong string.
"""
import html as html_mod
import io
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS = os.path.join(ROOT, 'static', 'js', 'app.js')
INDEX = os.path.join(ROOT, 'templates', 'index.html')

# Retired. These were a ratchet while Hindi caught up: a ceiling that could
# never rise, tightened each round. Coverage reached zero on both counts, so the
# ceiling is zero and the ratchet has become a plain requirement — an
# untranslated string is now a build failure rather than a budget line.
#
# If a future round genuinely needs to ship English text, raise these
# deliberately and say why. Do not delete them: a silently absent check is how
# this drifted the first time.
MAX_UNTRANSLATED_CALLS = 0
MAX_UNTRANSLATED_ATTRS = 0

# Entries that are legitimately identical in both languages. Each needs a
# reason, so the list cannot become a place to hide unfinished work.
SAME_IN_BOTH = {
    '⚡ HIIT': 'An acronym used as-is in Hindi fitness writing; transliterating '
              'it to एचआईआईटी would be less recognisable, not more.',
    'PostgreSQL': 'A product name. It is written PostgreSQL on the page you '
                  'would go to in order to install or configure it, so '
                  'transliterating it here would break the only link between '
                  'this line and everything else about it.',
    'SQLite, %1 MB': 'Same: SQLite is a product name, MB is an SI-derived unit '
                     'written the same way in Hindi and Bengali technical '
                     'text, and the size itself is a value.',
}


def _brace_match(text, open_at):
    depth, i = 0, open_at
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise AssertionError('unbalanced braces')


def _source():
    return io.open(APP_JS, encoding='utf-8').read()


def _split_i18n(src):
    """(i18n_object_text, rest_of_file)."""
    start = src.index('const I18N = {') + len('const I18N = ')
    end = _brace_match(src, start)
    return src[start:end + 1], src[end + 1:]


def _body_line_offset():
    """How many lines precede the code body, so a reported line number points at
    the real place in app.js rather than at an offset into a substring."""
    src = _source()
    end = _brace_match(src, src.index('const I18N = {') + len('const I18N = '))
    return src[:end + 1].count('\n')


# A comment is not a call. Without this, the explanation of why a mistake was
# fixed counts as the mistake — which is exactly what happened while writing
# these guards, twice.
_COMMENT_LINE = re.compile(r'\s*(//|\*|/\*)')


def _drop_comment_lines(text):
    return '\n'.join(ln for ln in text.split('\n')
                     if not _COMMENT_LINE.match(ln))


# Keys appear several per line, so this is deliberately NOT anchored. Both quote
# styles count: a key containing an apostrophe is naturally written with double
# quotes ("Today's Medicines"), and a checker that only saw single-quoted keys
# reported those as untranslated while the app resolved them perfectly well.
KEY = re.compile(r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*:""")


def _unescape(js_literal):
    """What the JS engine sees, not what the source file spells.

    A key written 'who\\'s responsible' is captured from the source with the
    backslash still in it, and comparing that to the real key — who's
    responsible — reports a translated string as missing. Only the escapes that
    actually appear in this pack are handled; anything more would be inventing a
    JavaScript parser to check a dictionary.
    """
    return (js_literal.replace("\\'", "'").replace('\\"', '"')
                      .replace('\\\\', '\\'))


# One key/value pair in a pack: 'key': 'value' or "key": 'value'.
# Groups: (single-quoted key, double-quoted key, value).
_PAIRS = re.compile(
    r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*:\s*'((?:[^'\\]|\\.)*)'""")


def _keys(text):
    return {_unescape(a or b) for a, b in KEY.findall(text)}
CALL = re.compile(r"\bt(?:format)?\(\s*'((?:[^'\\]|\\.)*)'")

# Functions that translate their own argument at the sink, so callers pass a
# bare English literal on purpose: showToast does `el.textContent = t(msg)`.
# That is a fine pattern, but it made 139 strings invisible to every check in
# this file — they LOOK untranslated, so nothing scanned them, and 127 of them
# had no Bengali at all while the pack reported itself complete. A sink call is
# a translation call; it belongs in the same set as an explicit one.
SINK = re.compile(
    r"\bshowToast\(\s*(?:'((?:[^'\\]|\\.){2,}?)'|\"((?:[^\"\\]|\\.){2,}?)\")")


I18N_DIR = os.path.join(ROOT, 'static', 'i18n')


def pack_path(code):
    return os.path.join(I18N_DIR, f'{code}.json')


def pack(code):
    """One language's pack, read from the JSON file the browser fetches.

    Packs used to live inside app.js and were parsed out of it with a regex.
    They are separate files now — bundling them made every English reader
    download every language — so this reads the same bytes the app does, which
    is both simpler and impossible to get subtly wrong.
    """
    import json
    with io.open(pack_path(code), encoding='utf-8') as fh:
        return json.load(fh)


def pack_keys(code):
    assert os.path.exists(pack_path(code)), f'the {code} pack is gone'
    return set(pack(code).keys())


def hindi_keys():
    return pack_keys('hi')


def listed_languages():
    """Languages the picker will actually offer, English aside. Read from
    SUPPORTED_LANGS rather than from the packs, because the question this file
    asks is "is everything we OFFER complete", not "is everything we happen to
    have translated"."""
    src = _source()
    block = src[src.index('const SUPPORTED_LANGS = ['):]
    block = block[:block.index(']')]
    out = []
    for line in block.splitlines():
        code = re.search(r"code:\s*'([a-z-]+)'", line)
        if not code or line.strip().startswith('//'):
            continue
        if code.group(1) == 'en':
            continue
        reviewed = re.search(r'reviewed:\s*(true|false)', line)
        out.append((code.group(1), reviewed.group(1) == 'true' if reviewed else None))
    return out


def used_strings():
    _, body = _split_i18n(_source())
    body = _drop_comment_lines(body)
    # Unescaped for the same reason the keys are: t('who\\'s here') looks up the
    # key who's here. Comparing raw source on one side and unescaped on the
    # other would report every apostrophe-bearing string as untranslated.
    out = {_unescape(s) for s in CALL.findall(body)}
    for sq, dq in SINK.findall(body):
        out.add(_unescape(sq or dq))
    return out


def template_strings():
    """Every string the template asks applyLang to translate.

    Both attributes, not just data-i18n. The placeholder form was missing here,
    so 17 placeholders were never checked against any pack — 16 of them had no
    Bengali and no Marathi, and the sign-in screen shipped with a translated
    label above an English "Your password". A placeholder is read by exactly the
    person who has not filled the field in yet.
    """
    raw = io.open(INDEX, encoding='utf-8').read()
    # Decoded, because getAttribute() returns the decoded value.
    return {html_mod.unescape(a)
            for a in re.findall(r'data-i18n(?:-ph|-aria|-title)?="([^"]*)"', raw)}


# ── The pack is real ────────────────────────────────────────────────────────

def test_the_hindi_pack_is_substantial():
    keys = hindi_keys()
    assert len(keys) > 2000, f'the Hindi pack shrank to {len(keys)} keys'


def test_no_translation_is_left_as_english():
    """An entry whose translation is identical to its English is usually a
    forgotten placeholder. A handful are legitimately the same — an acronym, a
    brand name — so this only flags entries with actual letters in them."""
    same = [en for en, tr in pack('hi').items()
            if en == tr and re.search(r'[A-Za-z]{4}', en)
            and en not in SAME_IN_BOTH]
    assert not same, ('these Hindi entries are still the English string: '
                      + ', '.join(same[:10]))


def test_every_same_in_both_entry_is_real_and_explained():
    """A stale exemption is worse than none — it silently stops checking."""
    hi = pack('hi')
    for key, reason in SAME_IN_BOTH.items():
        assert len(reason) > 40, f'{key} needs a real reason'
        assert key in hi, f'{key} is exempted but no longer in the pack'
        assert hi[key] == key, (
            f'{key} now has a real translation — remove it from SAME_IN_BOTH')


# ── The ratchet ─────────────────────────────────────────────────────────────

def test_untranslated_calls_do_not_grow():
    missing = sorted(used_strings() - hindi_keys())
    assert len(missing) <= MAX_UNTRANSLATED_CALLS, (
        f'{len(missing)} t()/tformat() strings have no Hindi (ceiling is '
        f'{MAX_UNTRANSLATED_CALLS}). Translate the new ones, or raise the '
        f'ceiling deliberately. First few: ' + '; '.join(missing[:8]))


def test_untranslated_attributes_do_not_grow():
    missing = sorted(template_strings() - hindi_keys())
    assert len(missing) <= MAX_UNTRANSLATED_ATTRS, (
        f'{len(missing)} data-i18n attributes have no Hindi (ceiling is '
        f'{MAX_UNTRANSLATED_ATTRS}). First few: ' + '; '.join(missing[:8]))


def test_the_ceilings_are_not_slack():
    """A ceiling far above the real number stops being a ratchet. It reached
    zero, so this now only guards against someone raising it again and leaving
    it raised after the strings were translated."""
    calls = len(used_strings() - hindi_keys())
    attrs = len(template_strings() - hindi_keys())
    assert MAX_UNTRANSLATED_CALLS - calls <= 15, (
        f'only {calls} strings are untranslated but the ceiling is '
        f'{MAX_UNTRANSLATED_CALLS} — lower it to {calls}')
    assert MAX_UNTRANSLATED_ATTRS - attrs <= 15, (
        f'only {attrs} attributes are untranslated but the ceiling is '
        f'{MAX_UNTRANSLATED_ATTRS} — lower it to {attrs}')


# ── Pages that must be complete ─────────────────────────────────────────────

# A function joins this list when its page is finished. After that, an
# untranslated string in it fails the build rather than shipping quietly.
REQUIRE_FULL_COVERAGE = [
    'load2fa', '_2faOffHtml', '_2faOnHtml', 'start2fa', 'confirm2fa',
    '_show2faRecoveryCodes', 'ask2faPassword', 'submit2faPassword',
    'loadBackups', 'runBackupNow', '_backupFailureText',
    'loadVisitPack', '_vpWindowLine', 'renderVisitPack', 'loadMedChanges',
    'renderPushControl', 'disablePushNotifications', 'enablePushNotifications',
    'loadTrash', 'loadStorage',
    'loadFalls', 'openFallForm', 'saveFall', '_fallsSummaryHtml',
    'loadHearing', 'openHearingForm', 'saveHearing',
    'loadRehab', 'openRehabForm', 'saveRehabPlan', 'logRehabSession',
    'toggleRehabSessions', 'deleteRehabSession',
]

TOP_LEVEL = re.compile(r'^(async function |function |const |let )')


def _function_body(lines, name):
    pat = re.compile(r'^(?:async )?function ' + re.escape(name) + r'\s*\(')
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines))
                if TOP_LEVEL.match(lines[j])), len(lines))
    return '\n'.join(lines[start:end])


@pytest.mark.parametrize('fn', REQUIRE_FULL_COVERAGE)
def test_a_finished_page_is_fully_translated(fn):
    lines = _source().split('\n')
    body = _function_body(lines, fn)
    assert body is not None, f'{fn} no longer exists — update the list'
    missing = sorted(set(CALL.findall(_drop_comment_lines(body))) - hindi_keys())
    assert not missing, (
        f'{fn} shows untranslated text to a Hindi reader: '
        + '; '.join(missing[:8]))


# ── Word order must live inside the string ──────────────────────────────────

# `${t('for')} ${value}` assumes English word order and cannot be translated
# correctly into a language that puts the preposition after the noun. This
# shipped once as "किसलिए cholesterol" — the Hindi interrogative "what for?"
# followed by a word — where the correct rendering is "cholesterol के लिए".
# The fix is always tformat('for %1', value), so the translator controls order.
# The separator class matters. The first version of this only matched whitespace
# between the fragment and the value, and missed `${t('typical')}: ${rng}` —
# which is the identical bug wearing a colon. Punctuation a label is glued to
# its value with is part of the phrase, so it belongs inside the translation too.
GLUED = re.compile(r"\$\{t\('([a-z][a-z ]{0,14})'\)\}[\s:\-–—=]*\$\{")

# Empty, and meant to stay that way. It briefly held nine older sites that were
# listed rather than fixed in the same breath as writing the guard; they have
# since been converted one at a time, each read in context first. An entry here
# is a temporary admission, not a permanent exemption — anything added needs a
# reason and a plan, because a list like this is how a guard quietly stops
# guarding.
KNOWN_GLUED = set()


def test_no_translated_fragment_is_glued_to_a_value():
    # Scanned line by line rather than over comment-stripped text: searching the
    # stripped copy and then counting newlines in the ORIGINAL reports whatever
    # happens to sit at that offset, which sent the first run of this test to two
    # innocent lines. Judging each line on its own keeps the number honest.
    _, body = _split_i18n(_source())
    offset = _body_line_offset()
    offenders = []
    for n, line_text in enumerate(body.split('\n')):
        if _COMMENT_LINE.match(line_text):
            continue
        for m in GLUED.finditer(line_text):
            frag = m.group(1)
            if frag in KNOWN_GLUED:
                continue
            offenders.append(f"{frag!r} (app.js line {offset + n + 1})")
    assert not offenders, (
        "a translated fragment is concatenated with a value, which forces "
        "English word order on every language. Use tformat('… %1', value) so "
        "the translation controls the order: " + "; ".join(offenders[:6]))


def test_every_listed_function_exists():
    """Otherwise the list quietly stops checking anything."""
    lines = _source().split('\n')
    gone = [fn for fn in REQUIRE_FULL_COVERAGE
            if _function_body(lines, fn) is None]
    assert not gone, 'listed but missing: ' + ', '.join(gone)


def test_the_known_glued_list_does_not_go_stale():
    """An entry that no longer appears means it was fixed — remove it, or the
    list slowly becomes a place where the guard is switched off."""
    _, body = _split_i18n(_source())
    clean = _drop_comment_lines(body)
    present = {m.group(1) for m in GLUED.finditer(clean)}
    gone = sorted(KNOWN_GLUED - present)
    assert not gone, ('these are listed as known-glued but no longer appear — '
                      'remove them from KNOWN_GLUED: ' + ', '.join(gone))


# ── Any language we offer, not just Hindi ───────────────────────────────────
# A partly-translated medical interface is worse than an English one: the reader
# cannot tell which half they are looking at, and the half that is missing is
# invisible. So the rule is not "translate as much as you can" — it is "a
# language appears in the picker only when its pack is complete".

def test_every_offered_language_has_a_pack():
    for code, _reviewed in listed_languages():
        keys = pack_keys(code)
        assert len(keys) > 100, f'{code} is offered but its pack is nearly empty'


@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_every_offered_language_is_complete(code):
    needed = used_strings() | template_strings()
    missing = sorted(needed - pack_keys(code))
    assert not missing, (
        f'{code} is offered in the language picker but {len(missing)} strings '
        f'have no translation, so those screens would silently fall back to '
        f'English mid-sentence. Either finish the pack or take the language out '
        f'of SUPPORTED_LANGS. First few: ' + '; '.join(m[:60] for m in missing[:6]))


@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_every_offered_language_declares_whether_it_was_reviewed(code):
    """An app that talks about doses in a language nobody fluent has checked can
    be confidently wrong, and the reader cannot tell. Saying so is the minimum."""
    declared = dict(listed_languages())
    assert declared[code] is not None, (
        f'{code} does not say whether a native speaker has read it — add '
        f'reviewed: true/false to its SUPPORTED_LANGS entry')


def test_an_unreviewed_language_says_so_in_the_app():
    src = _source()
    assert 'reviewed === false' in src, (
        'nothing checks the reviewed flag, so an unchecked translation would be '
        'presented exactly like a checked one')
    assert 'has not been checked by a native speaker' in src


@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_no_pack_leaves_entries_as_english(code):
    same = [en for en, tr in pack(code).items()
            if en == tr and re.search(r'[A-Za-z]{4}', en)
            and en not in SAME_IN_BOTH]
    assert not same, (f'{code} entries still hold the English string: '
                      + ', '.join(same[:10]))


@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_placeholders_survive_translation(code):
    """%1 and %2 are substituted at runtime. A translation that drops one prints
    nothing where a dose or a date should be; one that invents an extra prints a
    literal %3 at the user."""
    broken = [en for en, tr in pack(code).items()
              if set(re.findall(r'%\d', en)) != set(re.findall(r'%\d', tr))]
    assert not broken, (
        f'{code} translations change the placeholders, so a value would go '
        f'missing or a literal %n would be shown: ' + '; '.join(b[:60] for b in broken[:6]))


# ── Labels the server writes and the client translates ──────────────────────
#
# A third blind spot, and the subtlest. `t(m.timing_text)` translates a value
# the SERVER produced, so the string never appears as a literal anywhere in the
# JS — every scanner in this file walks straight past it. Five of the six
# timing labels had no Hindi and no Bengali, and the packs still reported
# themselves complete, because nothing knew to look for them.
#
# The fix is a registry: name the Python tables whose values reach a t() call,
# and read the values from the module itself so the list cannot drift from the
# source of truth. Adding a seventh timing label now fails this test until it
# is translated, which is the whole point.
#
# NOT a complete account of server-supplied text. Other endpoints send `label`
# fields that the client renders raw (the restore preview, donation kinds); they
# are a larger, separate piece of work and are deliberately not claimed here.
# What this covers is what goes through t().

def _timing_labels():
    from db.medicines import TIMING_LABELS
    return {v for v in TIMING_LABELS.values() if v}


def _readiness_strings():
    """Every name, cost and fix on the server-setup page.

    The page exists to tell someone what is broken and what to type. Half of it
    arriving in English would make it least useful to exactly the reader who
    needed a translated app in the first place.
    """
    from db.readiness import CHECKS
    return {s for c in CHECKS for s in (c['name'], c['cost'], c['fix'])}


# detail('...') templates are built at call time, so no runtime object holds
# them all — a check only produces its own. Read from the source instead, the
# same way the JS side is read, so a template added tomorrow is covered without
# anyone remembering to list it here.
_DETAIL_CALL = re.compile(r"\bdetail\(\s*'((?:[^'\\]|\\.)*)'")


def _readiness_details():
    src = io.open(os.path.join(ROOT, 'db', 'readiness.py'), encoding='utf-8').read()
    out = set()
    for line in src.splitlines():
        if line.lstrip().startswith('#'):
            continue
        for m in _DETAIL_CALL.finditer(line):
            s = _unescape(m.group(1))
            # '%1' alone is a passthrough for data (a hostname, an error
            # string) — there is nothing there to translate.
            if s.strip() != '%1':
                out.add(s)
    return out


def _export_section_names():
    """The card labels in the export view.

    A JS-side registry translated as `t(s.name)`, so the string is a variable at
    the call site and no scan can see it — the same blind spot as the Python
    tables below, on the other side of the wire. Read out of app.js so adding a
    twelfth section fails this test until it is translated.
    """
    src = _source()
    block = src[src.index('const EXPORT_SECTIONS = ['):]
    block = block[:block.index('\n];')]
    return {m.group(1) for line in block.splitlines()
            if not line.strip().startswith('//')
            for m in [re.search(r"name:\s*'((?:[^'\\]|\\.)*)'", line)] if m}


def _dormant_strings():
    """The name, unlocks sentence and step for each dormant-capability check.

    Written in Python and rendered with t()/tformat() on a variable, so no scan
    of the JS can see them — the same blind spot as the tables below.
    """
    from db.dormant import CHECKS
    return {s for c in CHECKS for s in (c['name'], c['unlocks'], c['step'])}


SERVER_LABELS = [
    ('db.dormant.CHECKS', _dormant_strings,
     'The dormant-capability panel. Names, unlocks lines and steps are Python '
     'strings passed through t() on the client.'),
    ('static/js/app.js EXPORT_SECTIONS', _export_section_names,
     'Export card labels. Rendered with t(s.name), so the literal never appears '
     'at a call site.'),
    ('db.medicines.TIMING_LABELS', _timing_labels,
     'Dose timing ("with food", "at bedtime"). Rendered through medTimingText, '
     'which calls t() on the server-supplied value.'),
    ('db.readiness.CHECKS', _readiness_strings,
     'The server-setup report. Names, costs and fixes are written in Python '
     'and passed through t() on the client.'),
    ("db.readiness detail('…')", _readiness_details,
     'Detail lines on the server-setup page. The server sends the template and '
     'its values separately; the client runs tformat() on them.'),
]


@pytest.mark.parametrize('where,values,why', SERVER_LABELS,
                         ids=[s[0] for s in SERVER_LABELS])
@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_server_supplied_labels_are_translated(code, where, values, why):
    missing = sorted(values() - pack_keys(code))
    assert not missing, (
        f'{where} — {why}\n'
        f'{code} has no translation for: '
        + '; '.join(m[:70] for m in missing[:6]))


def test_the_translating_chokepoint_still_exists():
    """The registry above is only true while medTimingText actually calls t().
    If someone inlines it back to a raw value, the labels stop being translated
    and every test here keeps passing — so assert the chokepoint itself."""
    src = _source()
    body = _function_body(src.split('\n'), 'medTimingText')
    assert body is not None, 'medTimingText is gone — update SERVER_LABELS'
    # Anchored so `t` must be its own identifier. A plain `'t(' in body` is
    # satisfied by the function's OWN NAME — medTimingTex*t(*m) — so the first
    # version of this test passed happily against a chokepoint I had deliberately
    # broken. A guard that cannot fail is worse than no guard: it reads as proof.
    assert re.search(r'(?<![A-Za-z0-9_$])t\(', body), (
        'medTimingText no longer translates its value, so server-supplied dose '
        'timings would render in English inside an otherwise translated app')


# ── Text that was never wrapped at all ──────────────────────────────────────
#
# Every check above asks "does this t() call have a translation". None of them
# could see a string that was never handed to t() in the first place — and that
# was the actual bug: the check-in card, the spoken briefing, the refill list
# and the notification panel were not partly translated, they were never wired.
# The packs reported themselves 100% complete the whole time, because a literal
# sitting between two tags is invisible to a scanner that only reads t(...).
#
# So this reads the other side: the text a template literal actually renders.
# It is deliberately scoped to a list of functions rather than the whole file —
# a whole-file version would need an exemption list longer than itself, and an
# exemption list is how a guard stops guarding. A function joins this list when
# its page has been wired, and then it cannot silently regress.

WIRED = [
    'renderCheckin', 'ciShowSummary', 'initDailyCheckin',
    'composeSpokenBriefing', 'renderRefillList', '_refillStatusLabel',
    'renderNotifications', 'timeAgo',
    'renderExportSections', 'updateExportEstimate',
]

_TAG = re.compile(r'<[^>]*>')
_ENTITY = re.compile(r'&[a-z]+;|&#\d+;')
_WORDS = re.compile(r"[A-Za-z][A-Za-z'’\-]*(?:\s+[A-Za-z][A-Za-z'’\-]*)*")

# Words that appear in rendered text but are not prose: bare HTML/CSS tokens
# that survive tag-stripping, and the handful of proper nouns the app shows
# untranslated on purpose.
_NOT_PROSE = re.compile(
    r'^(?:kcal|ml|mg|bpm|mmHg|km|kg|cm|BMI|BSA|MAP|WHtR|CSV|PDF|QR|SMS|'
    r'Arogo|HIIT)$')


def _strip_interpolations(s):
    """Replace ${...} with a marker, honouring nesting. What is left is the
    literal text — which is exactly the text that cannot be translated."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == '$' and i + 1 < n and s[i + 1] == '{':
            depth, i = 1, i + 2
            while i < n and depth:
                depth += {'{': 1, '}': -1}.get(s[i], 0)
                i += 1
            out.append('\x00')
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def _template_literals(body):
    """Backtick strings in `body`, with their ${} contents left in place so
    _strip_interpolations can remove them as units."""
    out, i, n = [], 0, len(body)
    while i < n:
        if body[i] != '`':
            i += 1
            continue
        j, depth, buf = i + 1, 0, []
        while j < n:
            c = body[j]
            if c == '\\':
                buf.append(body[j:j + 2])
                j += 2
                continue
            if c == '$' and j + 1 < n and body[j + 1] == '{':
                depth += 1
            elif c == '}' and depth:
                depth -= 1
            elif c == '`' and not depth:
                break
            buf.append(c)
            j += 1
        out.append(''.join(buf))
        i = j + 1
    return out


def _rendered_text(chunk):
    """The prose a template literal puts on screen, if any."""
    if '<' not in chunk:
        return []                       # a URL or a storage key, not markup
    t = _strip_interpolations(chunk)
    t = _TAG.sub('\x00', t)             # attributes go with the tag
    t = _ENTITY.sub(' ', t)
    found = []
    for seg in t.split('\x00'):
        for m in _WORDS.finditer(seg):
            w = m.group(0).strip()
            if len(w) >= 3 and not _NOT_PROSE.match(w):
                found.append(w)
    return found


@pytest.mark.parametrize('fn', WIRED)
def test_a_wired_function_renders_no_bare_english(fn):
    lines = _source().split('\n')
    body = _function_body(lines, fn)
    assert body is not None, f'{fn} no longer exists — update WIRED'
    bare = set()
    for chunk in _template_literals(_drop_comment_lines(body)):
        bare.update(_rendered_text(chunk))
    assert not bare, (
        f'{fn} renders text that was never passed to t(), so it stays English '
        f'in every language: ' + ', '.join(sorted(bare)[:10]))


# ── Text that lives in an attribute ─────────────────────────────────────────
#
# placeholder, aria-label and title are read by a person exactly like the text
# between the tags — and aria-label is read by the user who has no other way to
# find out what a control does. All three were untranslated app-wide: 49
# placeholders, 46 aria-labels, 34 titles, in an app that speaks four languages.
#
# A partly-tagged attribute layer is the failure this codebase keeps meeting —
# a list that looks complete because nothing counts what is missing. So this
# counts: every human-readable attribute value must carry its data-i18n-* twin.

_ATTR_PAIRS = [('placeholder', 'data-i18n-ph'),
               ('aria-label', 'data-i18n-aria'),
               ('title', 'data-i18n-title')]

# Values that are not prose and are correctly left alone. Each needs a reason.
_ATTR_EXEMPT = {
    'you@example.com': 'An email-shaped example. It is a format, not a phrase, '
                       'and it is recognisable in every script.',
    'Asia/Tokyo': 'An IANA time-zone identifier. It is a literal the browser '
                  'matches on, not a word — translating it breaks the lookup.',
}


def _attr_values(raw, attr):
    """Human-readable values of `attr`, comments stripped."""
    body = re.sub(r'<!--.*?-->', ' ', raw, flags=re.S)
    return {html_mod.unescape(v) for v in re.findall(attr + r'="([^"]+)"', body)
            if re.search(r'[A-Za-z]{3}', v)}


@pytest.mark.parametrize('attr,tag', _ATTR_PAIRS, ids=[a for a, _ in _ATTR_PAIRS])
def test_every_readable_attribute_is_tagged_for_translation(attr, tag):
    raw = io.open(INDEX, encoding='utf-8').read()
    untagged = sorted(_attr_values(raw, attr)
                      - _attr_values(raw, tag)
                      - set(_ATTR_EXEMPT))
    assert not untagged, (
        f'{len(untagged)} {attr} values have no {tag}, so they stay English in '
        f'every language: ' + '; '.join(repr(u) for u in untagged[:8]))


def test_the_attribute_exemptions_are_still_real():
    """An exemption list goes stale silently — that is how it stops being a
    list of decisions and becomes a place to hide work."""
    raw = io.open(INDEX, encoding='utf-8').read()
    present = set()
    for attr, _tag in _ATTR_PAIRS:
        present |= _attr_values(raw, attr)
    stale = sorted(set(_ATTR_EXEMPT) - present)
    assert not stale, f'exempted but no longer in the template: {stale}'
    for value, why in _ATTR_EXEMPT.items():
        assert len(why) > 25, f'{value!r} is exempted without a real reason'


def test_apply_lang_actually_writes_those_attributes():
    """Tagging without the runtime half changes nothing at all."""
    body = _drop_comment_lines(_function_body(_source().split('\n'), 'applyLang') or '')
    for _attr, tag in _ATTR_PAIRS:
        assert tag in body, f'applyLang never reads {tag}, so tagging it does nothing'
    for attr in ('placeholder', 'aria-label', 'title'):
        assert f"'{attr}'" in body, f'applyLang never writes {attr}'


# ── The front door ──────────────────────────────────────────────────────────
#
# The sign-in screen held 0 of the page's 627 translation tags, and the pack was
# not even fetched before it rendered — packs load on demand and that only
# happened after sign-in. So the app spoke four languages and its front door
# spoke one: set the app to Marathi, sign out, and come back to an English wall.
#
# Two separate failures, so two separate checks. Tagging the markup without
# loading the pack renders English anyway, and loading the pack without tagging
# the markup does nothing at all.

def test_the_sign_in_screen_is_tagged_for_translation():
    raw = io.open(INDEX, encoding='utf-8').read()
    start = raw.index('id="auth-screen"')
    # The auth screen ends where the app shell begins.
    end = raw.index('<div class="app-shell">', start)
    block = raw[start:end]
    tagged = len(re.findall(r'data-i18n(?:-ph)?=', block))
    assert tagged >= 15, (
        f'the sign-in screen carries only {tagged} translation tags. It is the '
        f'one screen every user sees before anything else, and it was English '
        f'for every language until 2026-08-29.')
    # And the strings a signed-out user actually reads must be among them.
    for must in ('Sign in', 'Create account', 'Forgot password?',
                 'Email address', 'Password'):
        assert f'data-i18n="{must}"' in block, f'{must!r} is not tagged'


def test_the_language_pack_loads_before_the_sign_in_screen():
    """A tagged screen with no pack loaded renders English and looks fine.

    Comments are stripped before looking. The first version of this checked
    `'loadLangPack' in body`, and the comment ABOVE the call explains why the
    call is there — so deleting the call left the test green. A guard that its
    own documentation can satisfy is not a guard.
    """
    src = _source()
    lines = src.split('\n')
    body = _drop_comment_lines(_function_body(lines, 'initAuth') or '')
    assert body, 'initAuth is gone — this check needs rewriting'
    assert 'loadLangPack(' in body, (
        'initAuth no longer loads the language pack, so the sign-in screen '
        'renders before any translation exists and falls back to English')
    shown = _drop_comment_lines(_function_body(lines, 'showAuthScreen') or '')
    assert 'applyLang(' in shown, (
        'showAuthScreen no longer re-applies the language. applyLang runs at '
        'DOMContentLoaded, BEFORE initAuth has fetched the pack, so without '
        'this the tags resolve to their English selves.')


# ── Dates follow the language too ───────────────────────────────────────────
#
# Translating every string still left "Friday, August 28" on a Hindi screen,
# because a date is not a string the pack ever sees — it is produced by
# toLocaleDateString, and 26 call sites had 'en-US' written into them. A
# translated app that dates everything in English is not translated; it is an
# English app wearing a pack. These two tests hold the fix in place: every
# language must carry a locale, and no call site may name one itself.

def test_every_language_declares_a_date_locale():
    """Including English. A language with no locale silently falls back to
    en-GB, which reads as working — the app switches, the dates do not."""
    src = _source()
    block = src[src.index('const SUPPORTED_LANGS = ['):]
    block = block[:block.index('\n];')]
    for line in block.splitlines():
        if line.strip().startswith('//') or 'code:' not in line:
            continue
        code = re.search(r"code:\s*'([a-z-]+)'", line).group(1)
        loc = re.search(r"locale:\s*'([A-Za-z-]+)'", line)
        assert loc, (
            f'{code} is offered but declares no date locale, so its dates would '
            f'render in English while the rest of the screen is translated')
        assert '-' in loc.group(1), (
            f'{code} has locale {loc.group(1)!r}; use a full BCP-47 tag like '
            f'hi-IN — region decides d/m/y vs m/d/y, not just month names')


# The two exceptions below are not date formatting:
#   - the comment recording why this rule exists
#   - nothing else, currently. Keep this list empty if you can.
_LOCALE_EXEMPT = ()


def test_no_date_key_is_built_from_utc():
    """`new Date().toISOString().slice(0,10)` is a UTC date, not a local one.

    Not an i18n rule as such, but it lives here because it is the same mistake
    in the same place: a date that looks right to whoever wrote it and is wrong
    for everyone east or west of them. In IST (UTC+5:30) it returns YESTERDAY
    between midnight and 5:30am — the notification panel grouped tonight's items
    under the wrong heading, and the export view set its end date to yesterday,
    silently leaving today's records out of the file.

    Use localToday() / localDateKey(d), which build the key from local parts.
    """
    bad = []
    for i, line in enumerate(_source().splitlines(), 1):
        if line.lstrip().startswith('//'):
            continue
        if re.search(r'toISOString\(\)\s*\.\s*slice\(\s*0\s*,\s*10\s*\)', line):
            bad.append(f'line {i}: {line.strip()[:90]}')
    assert not bad, (
        'these build a YYYY-MM-DD key from UTC, so they are a day off for part '
        'of every day outside UTC — use localToday() or localDateKey():\n  '
        + '\n  '.join(bad[:10]))


def test_no_date_is_formatted_with_a_hardcoded_locale():
    """toLocale*String(<literal>) pins that one date to one language forever,
    and it fails silently: the screen still renders, just in English."""
    bad = []
    # Walked over the WHOLE file, numbering as we go, and skipping comment lines
    # in place rather than stripping them first. Stripping renumbers everything
    # after the first comment, so the failure points at an innocent line — the
    # same trap the glued-fragment test above documents. A guard that names the
    # wrong line costs more time than no guard.
    for i, line in enumerate(_source().splitlines(), 1):
        if line.lstrip().startswith('//') or line.strip() in _LOCALE_EXEMPT:
            continue
        # A quoted tag, or the [] form — both mean "not the app's language".
        for m in re.finditer(r"toLocale\w*String\(\s*(?:'([^']*)'|\"([^\"]*)\"|\[\s*\])", line):
            bad.append(f'line {i}: {(m.group(1) or m.group(2) or "[]")}')
    assert not bad, (
        'these format a date or number with a fixed locale instead of '
        '_locale(), so they stay English no matter what language the user '
        'chose:\n  ' + '\n  '.join(bad[:12]))


# ── What the coverage number does NOT mean ──────────────────────────────────
#
# "Zero untranslated" means every string that ASKS to be translated has a
# translation. It does not mean there is no English on screen: a string that was
# never wrapped in t() and carries no data-i18n is invisible to this file, and
# was invisible on the dashboard for months — the onboarding checklist, the
# greeting, the calorie line and the read-aloud button all sat in English while
# the rest of the app spoke Hindi.
#
# Nothing static can find those in general; the reliable check is to switch the
# app to Hindi and look for Latin text. Doing that on the dashboard found 21
# such strings; wiring the checklist, the greeting and the calorie line brought
# it to 13. The named remainder — the notification banner, the daily briefing,
# the refill banner, the check-in card, parts of the todo list — has since been
# wired, and test_a_wired_function_renders_no_bare_english now holds those
# functions so they cannot drift back.
#
# The general problem is NOT solved. That test covers a declared list of
# functions, not the file; a sweep of every view found 147 distinct English
# strings, of which the ones above were a part. What is left is real and
# unmeasured here.
#
# So: "0 untranslated" here means "nothing that asked was refused". It does not
# mean the app speaks Hindi everywhere, and it should never be quoted as if it
# did.
#
# Server-side outbound text is a separate axis again: i18n_server.SERVER_LANGS
# is ('en', 'hi'), so a Bengali or Marathi user's dose reminders and emails
# arrive in English. normalize_lang() gates that deliberately — English is
# better than a half-rendered pack — but it is a gap, not a finished state.
#
# What CAN be pinned is the set already found and fixed, so they cannot revert.

DYNAMICALLY_TRANSLATED = [
    # Passed to t() as a variable, so the call-site scan cannot see the string.
    'Add your first medication', 'Connect a family member',
    'Log your first meal', 'Log a glass of water', 'Create a habit',
    'Good morning', 'Good afternoon', 'Good evening',
    'kcal remaining', 'kcal over budget', 'calories today',
    'Read aloud', 'Stop', 'Welcome to Arogo — %1/%2 done',
]


@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_dynamically_translated_strings_are_in_every_pack(code):
    """These reach t() as variables — FIRSTRUN_STEPS labels, the greeting, the
    calorie verdict. The call-site scan cannot see them, so they are listed by
    hand or they silently fall back to English."""
    missing = [s for s in DYNAMICALLY_TRANSLATED if s not in pack(code)]
    assert not missing, (
        f'{code} is missing strings that are translated dynamically: '
        + '; '.join(missing))


def test_those_strings_are_actually_still_used():
    """A list of hand-declared strings goes stale silently. Each of these must
    still appear in app.js, or it is dead weight pretending to be coverage."""
    src = _source()
    gone = [s for s in DYNAMICALLY_TRANSLATED
            if s.split('%1')[0][:24] not in src]
    assert not gone, ('these are declared as dynamically translated but no '
                      'longer appear in app.js: ' + '; '.join(gone))


def test_the_onboarding_checklist_goes_through_t():
    """It is the first screen anyone sees, and it was English for every Hindi
    reader who ever opened the app."""
    src = _source()
    assert '${t(s.label)}' in src, (
        'the first-run checklist renders its labels untranslated')
