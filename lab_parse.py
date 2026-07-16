"""
lab_parse.py — Read vital signs out of an uploaded lab report.

Today an uploaded report is a filing cabinet: it goes in and nothing comes
back. This pulls the readings the app already tracks (BP, glucose, pulse,
SpO2, temperature) out of the document so they can be offered to the user.

Two rules shape everything here:

  1. **Nothing is ever written automatically.** This module only ever
     *proposes*. A wrong number in a health chart is worse than no number,
     so the user confirms every reading before it becomes a vital.

  2. **Silence beats a guess.** A lab report is full of numbers that look
     like results and aren't — reference ranges, sample IDs, ages, phone
     numbers. Every pattern here demands an explicit label immediately
     before the value, with no other digits in between, and then a
     clinically plausible result. Anything else is dropped rather than
     surfaced for the user to catch.

Scope: digitally-generated PDFs (the overwhelming majority of lab portals
email these) plus text/CSV. Photos and scans need OCR, which needs a
system binary we don't ship — for those we say so plainly instead of
returning an empty list that reads like "your report has no readings".
"""
import re

try:
    from pypdf import PdfReader
except ImportError:                      # pragma: no cover - optional dep
    PdfReader = None


# ── Text extraction ───────────────────────────────────────────────────────────

# Below this, a "PDF" is really a scan wrapped in a PDF: the page yields a
# few stray characters from a letterhead and nothing else.
_MIN_TEXT_CHARS = 40

IMAGE_EXTS = {'png', 'jpg', 'jpeg'}


def extract_text(path: str, ext: str):
    """Return (text, reason). Exactly one is non-None.

    `reason` is user-facing copy explaining why there's nothing to read.
    """
    ext = (ext or '').lower().lstrip('.')

    if ext in IMAGE_EXTS:
        return None, "This is a photo, so we can't read the numbers out of it. You can still add the readings by hand."

    if ext in ('txt', 'csv'):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                return fh.read(), None
        except OSError:
            return None, "We couldn't open that file."

    if ext == 'pdf':
        if PdfReader is None:            # pragma: no cover - optional dep
            return None, "Reading PDFs isn't available on this server."
        try:
            reader = PdfReader(path)
            pages = []
            for page in reader.pages[:20]:      # a lab report is never 20+ pages
                try:
                    pages.append(page.extract_text() or '')
                except Exception:
                    continue                    # one bad page shouldn't sink the rest
            text = '\n'.join(pages)
        except Exception:
            return None, "We couldn't read that PDF — it may be password-protected or damaged."
        if len(text.strip()) < _MIN_TEXT_CHARS:
            return None, "This looks like a scan or photo rather than a digital report, so we can't read the numbers out of it."
        return text, None

    return None, "We can't read readings out of this file type yet."


# ── Reading patterns ──────────────────────────────────────────────────────────

# Label → value on the SAME line with no intervening digits. This is what
# keeps us on the result column: in "Glucose, Fasting  104  mg/dL  70 - 100"
# the first number after the label is the result; the reference range sits
# behind it and is never reached.
_GAP = r'[^\d\n]{0,40}?'
_NUM = r'(\d{1,3}(?:\.\d{1,2})?)'

# Plausible *result* windows — deliberately tighter than the database's
# anti-garbage bounds. A number outside these almost certainly means we
# locked onto the wrong column, so we drop it rather than propose it.
_PLAUSIBLE = {
    'blood_pressure': ((60, 260), (30, 160)),
    'heart_rate':     ((30, 220), None),
    'blood_sugar':    ((20, 600), None),
    'spo2':           ((50, 100), None),
}

_LABELS = {
    'blood_pressure': r'blood\s*pressure|\bb\.?\s?p\.?\b',
    'blood_sugar': (r'fasting\s+blood\s+(?:sugar|glucose)|blood\s+(?:sugar|glucose)|'
                    r'(?:random|fasting|postprandial|pp)\s+glucose|'
                    r'glucose(?:\s*[,(-]\s*(?:fasting|random|pp|f|r))?|\bfbs\b|\brbs\b|\bfpg\b'),
    'heart_rate':  r'heart\s*rate|pulse(?:\s*rate)?|\bhr\b',
    'spo2':        r'spo\s*[²2o0]|oxygen\s*saturation|o2\s*sat(?:uration)?',
    'temperature': r'temperature|\btemp\b',
}

_MMOL_TO_MGDL = 18.0182


def _lab(vtype):
    """Label alternation as one unit — bare `a|b` would bind past the value."""
    return '(?:' + _LABELS[vtype] + ')'


# The result column is sometimes blank (test pending, or a layout we misread).
# The first number on the row is then the reference range's lower bound — and
# a range floor is always a plausible-looking result, so nothing downstream
# would ever catch it. These two guards are what stop us reporting the lab's
# own reference band back to the user as their reading.

_RANGE_AFTER = re.compile(r'\s*(?:[-–—]|to\b)\s*\d')

def _is_range_bound(text, end_pos):
    """"70 - 100" is a band, not a reading — results are never written as ranges."""
    return bool(_RANGE_AFTER.match(text, end_pos))


_TARGET_BEFORE = re.compile(r'(?:[<>≤≥]|less\s+than|below|under|target)\s*$', re.I)

def _is_target(text, start_pos):
    """"< 120/80" is the goal printed on the form, not what the patient measured."""
    return bool(_TARGET_BEFORE.search(text[max(0, start_pos - 24):start_pos]))


def _plausible(vtype, v1, v2=None):
    bounds = _PLAUSIBLE.get(vtype)
    if not bounds:
        return True
    (lo1, hi1), b2 = bounds
    if not (lo1 <= v1 <= hi1):
        return False
    if b2 and v2 is not None and not (b2[0] <= v2 <= b2[1]):
        return False
    return True


def _context(text, match):
    """The source line, so the user can check our reading against the report."""
    start = text.rfind('\n', 0, match.start()) + 1
    end = text.find('\n', match.end())
    line = text[start:end if end != -1 else len(text)]
    line = re.sub(r'\s+', ' ', line).strip()
    return line[:120]


def find_readings(text: str) -> list:
    """Extract proposed vitals. Conservative by design: first hit per type."""
    if not text:
        return []
    # Normalise the whitespace that PDF extraction sprays around, but keep
    # newlines — they're the only thing telling us where a table row ends.
    text = re.sub(r'[ \t ]+', ' ', text)
    out = []

    def add(vtype, **kw):
        out.append(dict(type=vtype, **kw))

    def rejected(m):
        """A candidate that's really a reference band or a printed target."""
        return _is_range_bound(text, m.end(1)) or _is_target(text, m.start(1))

    # Blood pressure — the only two-value reading: "120/80"
    for m in re.finditer(_lab('blood_pressure') + _GAP + r'(\d{2,3})\s*/\s*(\d{2,3})',
                         text, re.I):
        sys_, dia = float(m.group(1)), float(m.group(2))
        if _is_target(text, m.start(1)) or sys_ <= dia \
                or not _plausible('blood_pressure', sys_, dia):
            continue                     # keep looking; a later row may be the real one
        add('blood_pressure', label='Blood pressure', value1=sys_, value2=dia,
            unit='mmHg', context=_context(text, m))
        break                            # first good hit wins

    # Blood sugar — mg/dL, or mmol/L converted (labs outside the US report mmol/L,
    # where an unconverted 5.6 would slip through as a plausible-looking number).
    for m in re.finditer(_lab('blood_sugar') + _GAP + _NUM + r'\s*(mg\s*/\s*d\s*l|mmol\s*/\s*l)?',
                         text, re.I):
        if rejected(m):
            continue
        val = float(m.group(1))
        note = ''
        if (m.group(2) or '').lower().replace(' ', '').startswith('mmol'):
            val = round(val * _MMOL_TO_MGDL)
            note = 'converted from mmol/L'
        if not _plausible('blood_sugar', val):
            continue
        add('blood_sugar', label='Blood sugar', value1=val, value2=None,
            unit='mg/dL', note=note, context=_context(text, m))
        break

    # Heart rate
    for m in re.finditer(_lab('heart_rate') + _GAP + r'(\d{2,3})\s*(bpm)?', text, re.I):
        val = float(m.group(1))
        if rejected(m) or not _plausible('heart_rate', val):
            continue
        add('heart_rate', label='Heart rate', value1=val, value2=None,
            unit='bpm', context=_context(text, m))
        break

    # SpO2
    for m in re.finditer(_lab('spo2') + _GAP + r'(\d{2,3})\s*%?', text, re.I):
        val = float(m.group(1))
        if rejected(m) or not _plausible('spo2', val):
            continue
        add('spo2', label='SpO₂', value1=val, value2=None,
            unit='%', context=_context(text, m))
        break

    # Temperature — the unit decides what the number means, so we only take a
    # reading we can place on a scale confidently (an explicit °C/°F, or a value
    # that can only be one of them). An ambiguous "Temperature 20" says nothing.
    for m in re.finditer(_lab('temperature') + _GAP + _NUM + r'\s*°?\s*([CF])?\b', text, re.I):
        if rejected(m):
            continue
        val = float(m.group(1))
        unit_raw = (m.group(2) or '').upper()
        if unit_raw == 'C' or (not unit_raw and 30 <= val <= 45):
            scale = '°C'
        elif unit_raw == 'F' or (not unit_raw and 90 <= val <= 110):
            scale = '°F'
        else:
            continue
        if (scale == '°C' and 30 <= val <= 45) or (scale == '°F' and 90 <= val <= 110):
            add('temperature', label='Temperature', value1=val, value2=None,
                unit=scale, context=_context(text, m))
            break

    return out
