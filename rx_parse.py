"""
rx_parse.py — Pull a medicine list out of a prescription.

Same philosophy as lab_parse: we'd rather surface less than surface something
wrong, and the user confirms every row before it becomes a medicine. Nothing is
added automatically.

Text PDFs / .txt (e-prescriptions from apps like 1mg, Practo) parse directly.
Photos/scans need OCR, which needs the `tesseract` binary + pytesseract — an
OPTIONAL dependency. If it isn't installed we say so instead of guessing; on a
self-hosted box you can `apt install tesseract-ocr` and it lights up. We never
send the image anywhere — OCR runs locally.
"""
import re

import lab_parse
from drug_data import DRUGS

try:                                       # optional local OCR
    import pytesseract
    from PIL import Image
    _OCR_AVAILABLE = True
except Exception:                          # pragma: no cover - optional dep
    _OCR_AVAILABLE = False


def ocr_available() -> bool:
    return _OCR_AVAILABLE


def extract_text(path: str, ext: str):
    """(text, reason) — exactly one non-None. Images go through OCR if present."""
    ext = (ext or '').lower().lstrip('.')
    if ext in lab_parse.IMAGE_EXTS:
        if not _OCR_AVAILABLE:
            return None, ("This is a photo. To read prescriptions from images, install "
                          "OCR (tesseract) on the server — otherwise add the medicines by hand.")
        try:
            txt = pytesseract.image_to_string(Image.open(path))
        except Exception:
            return None, "We couldn't read that photo. Try a clearer picture or add by hand."
        if len(txt.strip()) < 8:
            return None, "We couldn't make out any text in that photo. Add the medicines by hand."
        return txt, None
    # PDF / txt / csv — reuse the shared extractor.
    return lab_parse.extract_text(path, ext)


# ── Medicine extraction ───────────────────────────────────────────────────────

# Longest names first so "Amoxicillin + Clavulanate" wins over "Amoxicillin".
_NAMES = sorted({d['name'] for d in DRUGS}, key=len, reverse=True)
_NAME_RE = [(n, re.compile(r'\b' + re.escape(n) + r'\b', re.I)) for n in _NAMES]

_DOSE_RE = re.compile(r'(\d{1,4}(?:\.\d{1,2})?)\s*(mg|mcg|g|ml|iu|units?)\b', re.I)

# Frequency shorthand, most-specific first. The app caps at thrice-daily, so
# QID/four-times folds into that rather than inventing a fourth slot.
_FREQ = [
    (re.compile(r'\bt\.?d\.?s\.?\b|\bt\.?i\.?d\.?\b|\bq\.?i\.?d\.?\b|thrice|three times|four times|1\s*-\s*1\s*-\s*1', re.I), 'thrice_daily'),
    (re.compile(r'\bb\.?d\.?\b|\bb\.?i\.?d\.?\b|twice|two times|1\s*-\s*0\s*-\s*1|0\s*-\s*1\s*-\s*1|1\s*-\s*1\s*-\s*0', re.I), 'twice_daily'),
    (re.compile(r'weekly|once a week|once weekly', re.I), 'weekly'),
    (re.compile(r'\bo\.?d\.?\b|\bq\.?d\.?\b|\bh\.?s\.?\b|once daily|once a day|at night|bedtime|morning|1\s*-\s*0\s*-\s*0|0\s*-\s*0\s*-\s*1', re.I), 'once_daily'),
]

_UNITS = {'mg', 'mcg', 'g', 'ml', 'iu'}


def _frequency(context: str) -> str:
    for rx, val in _FREQ:
        if rx.search(context):
            return val
    return 'once_daily'


def find_medicines(text: str) -> list:
    """Candidate medicines from prescription text — deduped by drug name.

    Each item: {name, dosage, unit, frequency}. Dosage/frequency are best-effort
    from the same line; the confirmation UI lets the user fix anything.
    """
    if not text:
        return []
    out, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        for name, rx in _NAME_RE:
            if name.lower() in seen:
                continue
            if not rx.search(line):
                continue
            seen.add(name.lower())
            dose = _DOSE_RE.search(line)
            unit = dose.group(2).lower() if dose else 'mg'
            if unit.startswith('unit'):
                unit = 'iu'
            out.append({
                'name': name,
                'dosage': dose.group(1) if dose else '',
                'unit': unit if unit in _UNITS else 'mg',
                'frequency': _frequency(line),
            })
    return out
