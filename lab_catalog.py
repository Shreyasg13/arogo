"""
lab_catalog.py — a curated catalog of common lab tests with typical adult
reference ranges, weighted toward what's ordered most in India (HbA1c, lipids,
thyroid, vitamin D & B12, CBC, kidney/liver panels).

HONESTY NOTE: reference ranges genuinely vary by lab, assay, age, sex, and
pregnancy, and a doctor's *target* for a given person often differs from the
population "normal" (e.g. a diabetic's LDL target is lower). These are widely
used adult ranges for orientation only — the UI always frames an out-of-range
value as "worth discussing with your doctor," never as a diagnosis. Where sex
materially changes the range (haemoglobin, HDL, ferritin) we carry a separate
female range and pick by profile.

Each entry:
  key       stable id (also the trend key)
  name      display name
  unit      canonical unit
  low, high typical adult range (male/general)
  low_f,high_f  female range when it differs (else None → use low/high)
  category  grouping for the UI
  aliases   strings a report/search might use
"""

CATALOG = [
    # ── Diabetes / glucose ──────────────────────────────────────────────
    {'key': 'hba1c', 'name': 'HbA1c', 'unit': '%', 'low': 4.0, 'high': 5.6,
     'category': 'Diabetes', 'aliases': ['glycated haemoglobin', 'glycated hemoglobin', 'a1c', 'hb a1c']},
    {'key': 'fasting_glucose', 'name': 'Fasting glucose', 'unit': 'mg/dL', 'low': 70, 'high': 100,
     'category': 'Diabetes', 'aliases': ['fasting blood sugar', 'fbs', 'fasting plasma glucose']},
    {'key': 'pp_glucose', 'name': 'Post-meal glucose', 'unit': 'mg/dL', 'low': 70, 'high': 140,
     'category': 'Diabetes', 'aliases': ['postprandial', 'ppbs', 'pp blood sugar', '2 hour glucose']},

    # ── Lipids ──────────────────────────────────────────────────────────
    {'key': 'total_cholesterol', 'name': 'Total cholesterol', 'unit': 'mg/dL', 'low': 125, 'high': 200,
     'category': 'Lipids', 'aliases': ['cholesterol total', 'serum cholesterol']},
    {'key': 'ldl', 'name': 'LDL cholesterol', 'unit': 'mg/dL', 'low': 0, 'high': 100,
     'category': 'Lipids', 'aliases': ['ldl-c', 'low density lipoprotein']},
    {'key': 'hdl', 'name': 'HDL cholesterol', 'unit': 'mg/dL', 'low': 40, 'high': 60,
     'low_f': 50, 'high_f': 60,
     'category': 'Lipids', 'aliases': ['hdl-c', 'high density lipoprotein']},
    {'key': 'triglycerides', 'name': 'Triglycerides', 'unit': 'mg/dL', 'low': 0, 'high': 150,
     'category': 'Lipids', 'aliases': ['tg', 'serum triglycerides']},

    # ── Thyroid ─────────────────────────────────────────────────────────
    {'key': 'tsh', 'name': 'TSH', 'unit': 'mIU/L', 'low': 0.4, 'high': 4.0,
     'category': 'Thyroid', 'aliases': ['thyroid stimulating hormone', 'thyrotropin']},
    {'key': 'free_t4', 'name': 'Free T4', 'unit': 'ng/dL', 'low': 0.8, 'high': 1.8,
     'category': 'Thyroid', 'aliases': ['ft4', 'free thyroxine']},
    {'key': 'free_t3', 'name': 'Free T3', 'unit': 'pg/mL', 'low': 2.3, 'high': 4.2,
     'category': 'Thyroid', 'aliases': ['ft3', 'free triiodothyronine']},

    # ── Vitamins & minerals ─────────────────────────────────────────────
    {'key': 'vitamin_d', 'name': 'Vitamin D (25-OH)', 'unit': 'ng/mL', 'low': 30, 'high': 100,
     'category': 'Vitamins', 'aliases': ['25-hydroxy vitamin d', 'vit d', '25 oh vitamin d']},
    {'key': 'vitamin_b12', 'name': 'Vitamin B12', 'unit': 'pg/mL', 'low': 200, 'high': 900,
     'category': 'Vitamins', 'aliases': ['cobalamin', 'vit b12', 'b-12']},
    {'key': 'ferritin', 'name': 'Ferritin', 'unit': 'ng/mL', 'low': 30, 'high': 300,
     'low_f': 15, 'high_f': 150,
     'category': 'Vitamins', 'aliases': ['serum ferritin']},
    {'key': 'iron', 'name': 'Serum iron', 'unit': 'µg/dL', 'low': 60, 'high': 170,
     'category': 'Vitamins', 'aliases': ['serum iron']},

    # ── Complete blood count ────────────────────────────────────────────
    {'key': 'hemoglobin', 'name': 'Haemoglobin', 'unit': 'g/dL', 'low': 13.0, 'high': 17.0,
     'low_f': 12.0, 'high_f': 15.0,
     'category': 'Blood count', 'aliases': ['hb', 'hgb', 'haemoglobin', 'hemoglobin']},
    {'key': 'wbc', 'name': 'WBC count', 'unit': '/µL', 'low': 4000, 'high': 11000,
     'category': 'Blood count', 'aliases': ['white blood cell', 'total leucocyte count', 'tlc']},
    {'key': 'platelets', 'name': 'Platelet count', 'unit': '/µL', 'low': 150000, 'high': 450000,
     'category': 'Blood count', 'aliases': ['platelet', 'plt']},

    # ── Kidney ──────────────────────────────────────────────────────────
    {'key': 'creatinine', 'name': 'Creatinine', 'unit': 'mg/dL', 'low': 0.7, 'high': 1.3,
     'low_f': 0.6, 'high_f': 1.1,
     'category': 'Kidney', 'aliases': ['serum creatinine']},
    {'key': 'urea', 'name': 'Blood urea', 'unit': 'mg/dL', 'low': 15, 'high': 40,
     'category': 'Kidney', 'aliases': ['bun', 'blood urea nitrogen']},
    {'key': 'uric_acid', 'name': 'Uric acid', 'unit': 'mg/dL', 'low': 3.5, 'high': 7.2,
     'low_f': 2.6, 'high_f': 6.0,
     'category': 'Kidney', 'aliases': ['serum uric acid']},

    # ── Liver ───────────────────────────────────────────────────────────
    {'key': 'alt', 'name': 'ALT (SGPT)', 'unit': 'U/L', 'low': 7, 'high': 56,
     'category': 'Liver', 'aliases': ['sgpt', 'alanine aminotransferase']},
    {'key': 'ast', 'name': 'AST (SGOT)', 'unit': 'U/L', 'low': 5, 'high': 40,
     'category': 'Liver', 'aliases': ['sgot', 'aspartate aminotransferase']},
    {'key': 'bilirubin', 'name': 'Total bilirubin', 'unit': 'mg/dL', 'low': 0.1, 'high': 1.2,
     'category': 'Liver', 'aliases': ['serum bilirubin', 'bilirubin total']},
]

_BY_KEY = {t['key']: t for t in CATALOG}


def get_lab(key):
    return _BY_KEY.get(key)


def ref_range(key, gender=None):
    """(low, high) for a test, picking the female range when it differs and the
    profile says female. Returns (None, None) for an unknown key."""
    t = _BY_KEY.get(key)
    if not t:
        return (None, None)
    if gender == 'female' and t.get('low_f') is not None:
        return (t['low_f'], t['high_f'])
    return (t['low'], t['high'])


def status_for(key, value, gender=None):
    """'low' | 'high' | 'in_range' | None. Never a diagnosis — just where the
    number sits against the typical range, so the UI can flag it for a doctor."""
    lo, hi = ref_range(key, gender)
    if lo is None or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < lo:
        return 'low'
    if v > hi:
        return 'high'
    return 'in_range'


def search_labs(q, limit=8):
    """Name/alias search for the add-a-lab picker."""
    q = (q or '').strip().lower()
    if not q:
        return CATALOG[:limit]
    hits = []
    for t in CATALOG:
        hay = (t['name'] + ' ' + ' '.join(t.get('aliases', []))).lower()
        if q in hay:
            hits.append(t)
    return hits[:limit]


def categories():
    """Ordered unique category list for grouping in the UI."""
    seen, out = set(), []
    for t in CATALOG:
        if t['category'] not in seen:
            seen.add(t['category'])
            out.append(t['category'])
    return out
