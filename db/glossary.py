"""
db/glossary.py — a plain-language "what this measures" glossary.

Turns the cryptic terms on a lab report or vitals screen (HbA1c, ALT, TSH, SpO2…)
into one plain sentence each. Personalised: it leads with the terms YOU actually
have — your logged labs, the vitals you track, your own medicines — and can also
browse the full reference set.

HONESTY (load-bearing, matches lab_catalog.py:6-12): every entry describes what a
test *measures*, nothing more. No normal/abnormal judgement, no ranges-as-verdicts
(ranges live in the Labs view with their honest status), no causes, no treatment
advice, no "you're fine / not fine". Descriptions are standard, non-controversial
facts about what the test is — not interpretations of your value. Medicine notes
come only from the curated local formulary (drug_data.py); a drug we don't
recognise is shown by name with no invented description.
"""
from __future__ import annotations

from .core import execute, current_user_id

# What each lab test measures — plain, neutral, definitional. Keys match
# lab_catalog.CATALOG exactly.
LAB_GLOSSARY = {
    'hba1c': "An average of your blood sugar over roughly the past 2–3 months, shown as a percentage — one number instead of many daily readings.",
    'fasting_glucose': "Your blood sugar measured after not eating for several hours, usually overnight.",
    'pp_glucose': "Your blood sugar measured about two hours after a meal.",
    'total_cholesterol': "The total amount of cholesterol, a fatty substance, carried in your blood.",
    'ldl': "One type of cholesterol carried in the blood, often labelled the 'bad' cholesterol.",
    'hdl': "One type of cholesterol carried in the blood, often labelled the 'good' cholesterol.",
    'triglycerides': "A type of fat (lipid) carried in your blood, usually measured after fasting.",
    'tsh': "A hormone from the pituitary gland that signals the thyroid how much thyroid hormone to make — used to check thyroid function.",
    'free_t4': "One of the main thyroid hormones (thyroxine), measured in its active 'free' form.",
    'free_t3': "One of the main thyroid hormones (triiodothyronine), measured in its active 'free' form.",
    'vitamin_d': "The level of vitamin D stored in your body, measured as 25-hydroxy vitamin D.",
    'vitamin_b12': "The level of vitamin B12, a vitamin your nerves and red blood cells need.",
    'ferritin': "A protein that stores iron — it reflects how much iron your body has in reserve.",
    'iron': "The amount of iron circulating in your blood.",
    'hemoglobin': "The protein in red blood cells that carries oxygen around your body.",
    'wbc': "The number of white blood cells, which are part of your immune system.",
    'platelets': "The number of platelets, the cell fragments that help your blood clot.",
    'creatinine': "A waste product from your muscles that the kidneys filter out — used to gauge how well the kidneys are working.",
    'urea': "A waste product your kidneys remove from the blood; also reported as blood urea nitrogen (BUN).",
    'uric_acid': "A waste product made when the body breaks down substances called purines.",
    'alt': "An enzyme found mainly in the liver, released into the blood when liver cells are under stress — used to check liver health.",
    'ast': "An enzyme found in the liver and muscles, used alongside ALT to check liver health.",
    'bilirubin': "A yellow substance made when old red blood cells break down; the liver processes and clears it.",
}

# The vitals the app tracks. type → plain description.
VITAL_GLOSSARY = {
    'blood_pressure': "The pressure of blood against your artery walls. The top number (systolic) is during a heartbeat; the bottom (diastolic) is between beats.",
    'blood_sugar': "The amount of glucose (sugar) in your blood at the moment it is measured.",
    'heart_rate': "How many times your heart beats per minute.",
    'spo2': "The percentage of oxygen your red blood cells are carrying, read by a fingertip sensor.",
    'temperature': "Your body temperature.",
    'weight': "Your body weight.",
}
_VITAL_LABEL = {
    'blood_pressure': 'Blood pressure', 'blood_sugar': 'Blood sugar', 'heart_rate': 'Heart rate',
    'spo2': 'Oxygen (SpO₂)', 'temperature': 'Temperature', 'weight': 'Weight',
}
_VITAL_UNIT = {
    'blood_pressure': 'mmHg', 'blood_sugar': 'mg/dL', 'heart_rate': 'bpm',
    'spo2': '%', 'temperature': '°C', 'weight': 'kg',
}


def _lab_entry(cat_row):
    return {
        'key': cat_row['key'],
        'term': cat_row['name'],
        'unit': cat_row.get('unit', ''),
        'category': cat_row.get('category', ''),
        'plain': LAB_GLOSSARY.get(cat_row['key']),
        'aka': [a for a in (cat_row.get('aliases') or []) if a.lower() != cat_row['name'].lower()][:3],
    }


def _all_labs():
    from lab_catalog import CATALOG
    return [_lab_entry(r) for r in CATALOG]


def _all_vitals():
    return [{'key': k, 'term': _VITAL_LABEL.get(k, k), 'unit': _VITAL_UNIT.get(k, ''),
             'plain': v} for k, v in VITAL_GLOSSARY.items()]


def _drug_hint_map():
    """name(lower) → plain-language hint, from the curated local formulary only."""
    try:
        from drug_data import DRUGS
        return {d['name'].strip().lower(): d.get('hint', '') for d in DRUGS if d.get('name')}
    except Exception:
        return {}


def get_glossary():
    """Plain-language definitions, leading with the terms this user actually has.
    Descriptive only — see the module docstring for the honesty contract."""
    uid = current_user_id()

    # Labs the user has recorded → their glossary entry (catalog terms only; a
    # free-text lab we don't recognise is never given an invented description).
    try:
        from .labs import get_latest_by_test
        from lab_catalog import _BY_KEY
        yours_labs = []
        seen = set()
        for r in (get_latest_by_test() or []):
            k = r.get('lab_key')
            if k in _BY_KEY and k not in seen:
                seen.add(k)
                yours_labs.append(_lab_entry(_BY_KEY[k]))
    except Exception:
        yours_labs = []

    # Vitals the user has any data for.
    try:
        rows = execute("SELECT DISTINCT type FROM vitals WHERE user_id=?", (uid,), fetchall=True) or []
        have = {r['type'] for r in rows}
        yours_vitals = [{'key': k, 'term': _VITAL_LABEL.get(k, k), 'unit': _VITAL_UNIT.get(k, ''),
                         'plain': VITAL_GLOSSARY[k]} for k in VITAL_GLOSSARY if k in have]
    except Exception:
        yours_vitals = []

    # The user's own medicines, annotated ONLY from the curated formulary.
    try:
        hints = _drug_hint_map()
        meds = execute("SELECT DISTINCT name FROM medicines WHERE user_id=?", (uid,), fetchall=True) or []
        yours_meds = []
        for m in meds:
            name = (m['name'] or '').strip()
            if not name:
                continue
            yours_meds.append({'term': name, 'plain': hints.get(name.lower())})
    except Exception:
        yours_meds = []

    return {
        'yours': {'labs': yours_labs, 'vitals': yours_vitals, 'medicines': yours_meds},
        'all': {'labs': _all_labs(), 'vitals': _all_vitals()},
    }
