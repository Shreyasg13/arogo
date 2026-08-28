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


def pack_keys(code):
    """The keys in one language's pack."""
    i18n, _ = _split_i18n(_source())
    m = re.search(r"^\s{2}" + re.escape(code) + r":\s*\{", i18n, re.M)
    assert m, f'the {code} pack is gone'
    end = _brace_match(i18n, m.end() - 1)
    return _keys(i18n[m.end():end])


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
    # Unescaped for the same reason the keys are: t('who\\'s here') looks up the
    # key who's here. Comparing raw source on one side and unescaped on the
    # other would report every apostrophe-bearing string as untranslated.
    return {_unescape(s) for s in CALL.findall(_drop_comment_lines(body))}


def template_strings():
    raw = io.open(INDEX, encoding='utf-8').read()
    # Decoded, because getAttribute() returns the decoded value.
    return {html_mod.unescape(a) for a in re.findall(r'data-i18n="([^"]*)"', raw)}


# ── The pack is real ────────────────────────────────────────────────────────

def test_the_hindi_pack_is_substantial():
    keys = hindi_keys()
    assert len(keys) > 2000, f'the Hindi pack shrank to {len(keys)} keys'


def test_no_translation_is_left_as_english():
    """An entry whose Hindi is identical to its English is usually a forgotten
    placeholder. A handful are legitimately the same — a number format, a brand
    name — so this only flags entries with actual letters in them."""
    i18n, _ = _split_i18n(_source())
    m = re.search(r"^\s{2}hi:\s*\{", i18n, re.M)
    block = i18n[m.end():_brace_match(i18n, m.end() - 1)]
    pairs = re.findall(r"'((?:[^'\\]|\\.)*)'\s*:\s*'((?:[^'\\]|\\.)*)'", block)
    same = [en for en, hi in pairs
            if en == hi and re.search(r'[A-Za-z]{4}', en)
            and en not in SAME_IN_BOTH]
    assert not same, ('these Hindi entries are still the English string: '
                      + ', '.join(same[:10]))


def test_every_same_in_both_entry_is_real_and_explained():
    """A stale exemption is worse than none — it silently stops checking."""
    i18n, _ = _split_i18n(_source())
    m = re.search(r"^\s{2}hi:\s*\{", i18n, re.M)
    block = i18n[m.end():_brace_match(i18n, m.end() - 1)]
    pairs = dict(re.findall(r"'((?:[^'\\]|\\.)*)'\s*:\s*'((?:[^'\\]|\\.)*)'", block))
    for key, reason in SAME_IN_BOTH.items():
        assert len(reason) > 40, f'{key} needs a real reason'
        assert key in pairs, f'{key} is exempted but no longer in the pack'
        assert pairs[key] == key, (
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
    i18n, _ = _split_i18n(_source())
    m = re.search(r"^\s{2}" + re.escape(code) + r":\s*\{", i18n, re.M)
    block = i18n[m.end():_brace_match(i18n, m.end() - 1)]
    pairs = _PAIRS.findall(block)
    same = [_unescape(a or b) for a, b, val in pairs
            if _unescape(a or b) == _unescape(val)
            and re.search(r'[A-Za-z]{4}', a or b)
            and _unescape(a or b) not in SAME_IN_BOTH]
    assert not same, (f'{code} entries still hold the English string: '
                      + ', '.join(same[:10]))


@pytest.mark.parametrize('code', [c for c, _ in listed_languages()])
def test_placeholders_survive_translation(code):
    """%1 and %2 are substituted at runtime. A translation that drops one prints
    nothing where a dose or a date should be; one that invents an extra prints a
    literal %3 at the user."""
    i18n, _ = _split_i18n(_source())
    m = re.search(r"^\s{2}" + re.escape(code) + r":\s*\{", i18n, re.M)
    block = i18n[m.end():_brace_match(i18n, m.end() - 1)]
    pairs = _PAIRS.findall(block)
    broken = []
    for a, b, val in pairs:
        en, tr = _unescape(a or b), _unescape(val)
        if set(re.findall(r'%\d', en)) != set(re.findall(r'%\d', tr)):
            broken.append(en)
    assert not broken, (
        f'{code} translations change the placeholders, so a value would go '
        f'missing or a literal %n would be shown: ' + '; '.join(b[:60] for b in broken[:6]))
