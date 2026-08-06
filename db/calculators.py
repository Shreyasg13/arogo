"""
db/calculators.py — derived health numbers from data the user already gave us.

Every value is a plain, universally-agreed formula (shown to the user), computed
only from their own profile/readings, and returns None when an input is missing —
never a guess. We deliberately DON'T compute anything whose constants we can't
vouch for (e.g. eGFR / body-fat regressions); a wrong kidney or body-fat number
is worse than no number.
"""
from __future__ import annotations
import math

from .core import current_user_id, to_num
from .food import get_profile


def _bmi_category(bmi: float) -> str:
    if bmi < 18.5: return 'Underweight'
    if bmi < 25:   return 'Normal'
    if bmi < 30:   return 'Overweight'
    return 'Obese'


def _asia_category(bmi: float) -> str:
    # WHO Asia-Pacific cut-offs, relevant for South-Asian bodies.
    if bmi < 18.5: return 'Underweight'
    if bmi < 23:   return 'Normal'
    if bmi < 27.5: return 'Overweight'
    return 'Obese'


def get_health_calculators() -> dict:
    """BMI (+ ideal-weight range), body-surface area, and mean arterial pressure —
    whichever the user has the inputs for. Each item carries its formula and the
    inputs it used; missing-input items are simply absent."""
    from .health import get_vitals

    p = get_profile() or {}
    w = to_num(p.get('weight_kg'), 0) or None      # 0/None/blank → not provided
    h = to_num(p.get('height_cm'), 0) or None
    items = []

    # BMI — weight(kg) / height(m)^2.
    if w and h and w > 0 and h > 0:
        hm = h / 100.0
        bmi = round(w / (hm * hm), 1)
        lo = round(18.5 * hm * hm, 1)
        hi = round(24.9 * hm * hm, 1)
        items.append({
            'key': 'bmi', 'label': 'BMI', 'value': bmi, 'unit': 'kg/m²',
            'category': _bmi_category(bmi), 'asia_category': _asia_category(bmi),
            'note': f'Healthy weight for your height: {lo}–{hi} kg',
            'formula': 'weight ÷ height²',
        })

    # Body-surface area — Mosteller: √(height_cm × weight_kg / 3600).
    if w and h and w > 0 and h > 0:
        bsa = round(math.sqrt(h * w / 3600.0), 2)
        items.append({
            'key': 'bsa', 'label': 'Body-surface area', 'value': bsa, 'unit': 'm²',
            'note': 'Used by clinicians for some medication dosing.',
            'formula': '√(height × weight ÷ 3600) — Mosteller',
        })

    # Mean arterial pressure — from the most recent BP reading (needs both numbers).
    bp = None
    for v in get_vitals('blood_pressure', days=120):
        if v.get('value1') and v.get('value2'):
            bp = v
            break
    if bp:
        sbp = to_num(bp['value1'], 0) or None
        dbp = to_num(bp['value2'], 0) or None
        if sbp and dbp and sbp >= dbp:
            mapv = round(dbp + (sbp - dbp) / 3.0)
            items.append({
                'key': 'map', 'label': 'Mean arterial pressure', 'value': mapv, 'unit': 'mmHg',
                'note': f'From your {int(sbp)}/{int(dbp)} reading on {bp.get("date_key", "")}',
                'formula': 'diastolic + (systolic − diastolic) ÷ 3',
            })

    # What's still needed, so the UI can nudge instead of just showing blanks.
    missing = []
    if not (w and h):
        missing.append('height and weight in your profile')
    if not bp:
        missing.append('a blood-pressure reading')

    return {'calculators': items, 'has_data': bool(items), 'missing': missing}
