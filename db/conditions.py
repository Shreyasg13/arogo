"""
db/conditions.py — condition dashboards.

Ties together, for one chronic condition, the data that's otherwise scattered
across tabs: the relevant lab results, the relevant vital, the medicines that
treat it, and (for PCOS) cycle regularity + symptoms. Nothing new is stored —
this is a focused *read* over labs, vitals, medicines, and cycle. No diagnosis,
no targets of our own; lab status still comes from lab_catalog's typical ranges.
"""
import re

from .core import execute, current_user_id
import lab_catalog

# Each condition maps to the signals that matter for it. med_keywords match a
# medicine's name OR purpose (case-insensitive substring) — India-weighted brand
# and generic names. cycle=True pulls the menstrual signals for PCOS.
CONDITIONS = {
    'diabetes': {
        'name': 'Diabetes', 'emoji': '🩸',
        'labs': ['hba1c', 'fasting_glucose', 'pp_glucose'],
        'vitals': ['blood_sugar'],
        'med_keywords': ['metformin', 'glimepiride', 'gliclazide', 'sitagliptin',
                         'insulin', 'glycomet', 'janumet', 'diabetes', 'diabetic'],
        'blurb': 'Your sugar readings, HbA1c, and the medicines that manage them.',
    },
    'hypertension': {
        'name': 'Blood pressure', 'emoji': '🫀',
        'labs': ['creatinine'],
        'vitals': ['blood_pressure'],
        'med_keywords': ['amlodipine', 'telmisartan', 'losartan', 'ramipril',
                         'atenolol', 'olmesartan', 'metoprolol', 'cilnidipine',
                         'pressure', 'bp', 'hypertension'],
        'blurb': 'Your blood-pressure readings and the medicines that manage them.',
    },
    'thyroid': {
        'name': 'Thyroid', 'emoji': '🦋',
        'labs': ['tsh', 'free_t4', 'free_t3'],
        'vitals': [],
        'med_keywords': ['thyroxine', 'levothyroxine', 'thyronorm', 'eltroxin',
                         'thyroid', 'carbimazole'],
        'blurb': 'Your thyroid labs (TSH, T4, T3) and thyroid medicine.',
    },
    'cholesterol': {
        'name': 'Cholesterol', 'emoji': '🫧',
        'labs': ['total_cholesterol', 'ldl', 'hdl', 'triglycerides'],
        'vitals': [],
        'med_keywords': ['atorvastatin', 'rosuvastatin', 'statin', 'ezetimibe',
                         'fenofibrate', 'cholesterol'],
        'blurb': 'Your lipid panel and any cholesterol medicine.',
    },
    'pcos': {
        'name': 'PCOS', 'emoji': '🌸',
        'labs': ['tsh', 'vitamin_d'],
        'vitals': [],
        'med_keywords': ['metformin', 'inositol', 'myo-inositol', 'spironolactone',
                         'ocp', 'pcos'],
        'cycle': True,
        'blurb': 'Cycle regularity, symptoms, and the labs/medicines that go with PCOS.',
    },
}


def list_conditions() -> list:
    return [{'key': k, 'name': v['name'], 'emoji': v['emoji'], 'blurb': v['blurb']}
            for k, v in CONDITIONS.items()]


def _latest_labs(keys, gender):
    """Latest value + status per requested lab key (missing ones flagged)."""
    out = []
    uid = current_user_id()
    for key in keys:
        r = execute("""SELECT value, unit, date_key FROM lab_results
                       WHERE user_id=? AND lab_key=? ORDER BY date_key DESC, created_at DESC LIMIT 1""",
                    (uid, key), fetchone=True)
        meta = lab_catalog.get_lab(key)
        lo, hi = lab_catalog.ref_range(key, gender)
        out.append({
            'key': key, 'name': meta['name'] if meta else key,
            'unit': meta['unit'] if meta else '',
            'ref_low': lo, 'ref_high': hi,
            'value': r['value'] if r else None,
            'date': r['date_key'] if r else None,
            'status': lab_catalog.status_for(key, r['value'], gender) if r else None,
            'have': bool(r),
        })
    return out


def _latest_vitals(types):
    out = []
    uid = current_user_id()
    for vt in types:
        r = execute("""SELECT value1, value2, unit, date_key FROM vitals
                       WHERE user_id=? AND type=? ORDER BY logged_at DESC LIMIT 1""",
                    (uid, vt), fetchone=True)
        out.append({'type': vt, 'have': bool(r),
                    'value1': r['value1'] if r else None,
                    'value2': r['value2'] if r else None,
                    'unit': r['unit'] if r else '',
                    'date': r['date_key'] if r else None})
    return out


def _matching_meds(keywords):
    uid = current_user_id()
    rows = execute("SELECT name, dosage, purpose FROM medicines WHERE user_id=? AND active=1",
                   (uid,), fetchall=True) or []
    # Match WHOLE WORDS, not substrings — otherwise 'statin' matches "Nystatin"
    # (an antifungal → Cholesterol), 'sugar' matches "Sugarfree" (→ Diabetes), and
    # 'bp' matches "BPH" meds (→ Blood pressure). Mislabelling a medicine under a
    # condition is exactly the dishonesty to avoid in a health app.
    kws = [re.escape(k.strip().lower()) for k in keywords if k and k.strip()]
    if not kws:
        return []
    rx = re.compile(r'\b(?:' + '|'.join(kws) + r')\b')
    out = []
    for r in rows:
        hay = (str(r['name'] or '') + ' ' + str(r['purpose'] or '')).lower()
        if rx.search(hay):
            out.append({'name': r['name'], 'dosage': r['dosage'], 'purpose': r['purpose']})
    return out


def get_condition_dashboard(key) -> dict:
    cfg = CONDITIONS.get(key)
    if not cfg:
        raise ValueError('Unknown condition')
    prof = execute("SELECT gender FROM user_profile WHERE user_id=? LIMIT 1",
                   (current_user_id(),), fetchone=True)
    gender = prof['gender'] if prof else None

    out = {
        'key': key, 'name': cfg['name'], 'emoji': cfg['emoji'], 'blurb': cfg['blurb'],
        'labs': _latest_labs(cfg['labs'], gender),
        'vitals': _latest_vitals(cfg['vitals']),
        'medicines': _matching_meds(cfg['med_keywords']),
    }
    if cfg.get('cycle'):
        # Cycle data is a private "diary" category — walled from a caregiver who
        # is managing this member (see auth._ACTING_AS_PRIVATE / /api/cycle). The
        # condition dashboard must honour that same wall: surface the cycle block
        # only when the member is viewing their OWN account, never while someone
        # is acting-as them. Labs/vitals/meds above stay visible (a caregiver
        # managing meds is meant to see those).
        if _acting_as_someone():
            out['cycle'] = None
            out['cycle_private'] = True
        else:
            from .cycle import get_cycle_summary, get_symptom_summary
            summary = get_cycle_summary()
            out['cycle'] = {'regularity': summary.get('regularity'),
                            'cycle_length': summary.get('cycle_length'),
                            'symptoms': get_symptom_summary().get('top', [])[:4]}
    return out


def _acting_as_someone():
    """True when the current request is a caregiver managing a family member
    (acting-as). Safe outside a request context (returns False)."""
    try:
        from flask import g, has_request_context
        return bool(has_request_context() and getattr(g, 'acting_as', None))
    except Exception:
        return False
