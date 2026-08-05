"""
db/health_id.py — a printable, show-at-the-hospital health ID card.

Composes data the user already has into one wallet-style card:
  • identity from the profile (name, age, sex, height/weight)
  • critical info from the emergency card (blood type, allergies, conditions)
  • the user's ACTUAL active medicines pulled live from the medication tracker

That last part is the point: the emergency card's "medications" box is free
text a user has to remember to update, so it drifts. The ID card instead reads
the real active-medicine list, so what's printed is what they actually take.

Purely read-only and honest — nothing invented. Fields the user hasn't filled
in simply don't appear on the card.
"""
from .core import execute, current_user_id
from .health import get_emergency_info


def _s(v):
    return (v or '').strip() if isinstance(v, str) else (v or '')


def get_health_id() -> dict:
    uid = current_user_id()
    prof = execute("SELECT name, age, gender, weight_kg, height_cm "
                   "FROM user_profile WHERE user_id=? LIMIT 1", (uid,), fetchone=True)
    prof = dict(prof) if prof else {}
    e = get_emergency_info()

    meds = execute("""SELECT name, dosage, unit, frequency FROM medicines
                      WHERE user_id=? AND active=1 ORDER BY name""", (uid,), fetchall=True) or []
    active_medicines = [{
        'name': _s(m['name']),
        'dose': (_s(m['dosage']) + ' ' + _s(m['unit'])).strip(),
        'frequency': _s(m['frequency']),
    } for m in meds if _s(m['name'])]

    contacts = []
    for n, p in ((e.get('contact1_name'), e.get('contact1_phone')),
                 (e.get('contact2_name'), e.get('contact2_phone'))):
        if _s(n) or _s(p):
            contacts.append({'name': _s(n), 'phone': _s(p)})

    return {
        'identity': {
            'name': _s(prof.get('name')),
            'age': prof.get('age'),
            'gender': _s(prof.get('gender')),
            'weight_kg': prof.get('weight_kg'),
            'height_cm': prof.get('height_cm'),
        },
        'blood_type': _s(e.get('blood_type')),
        'allergies': _s(e.get('allergies')),
        'conditions': _s(e.get('conditions')),
        'notes_medications': _s(e.get('medications')),   # free text (e.g. meds not in Arogo)
        'active_medicines': active_medicines,            # live from the tracker
        'contacts': contacts,
        'insurance': {
            'provider': _s(e.get('insurance_provider')),
            'number': _s(e.get('insurance_number')),
        },
    }
