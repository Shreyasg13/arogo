"""
db/health_binder.py — N2 always-current health binder.

One read-only, printable summary of the user's CURRENT health picture, for a new
doctor, a hospital admission, or the ER. Where the health-ID card is a wallet
snapshot, the binder is the full page: identity + blood type + advance-care
wishes, the live active-medicine list, allergies, the conditions the user
recorded, their most recent lab values, vaccines on record, emergency contacts,
and dental/vision (next checkup + current glasses Rx).

Everything is composed from data the user already entered — nothing is invented,
scored, or interpreted. Empty sections simply don't appear. Reuses get_health_id
so the identity / meds / allergy logic stays in one place.
"""
from .core import current_user_id
from .health_id import get_health_id


def get_health_binder() -> dict:
    import datetime as dt

    hid = get_health_id()

    # Recent labs — most-recent value per test, trimmed to the freshest dozen.
    labs = []
    try:
        from .labs import get_latest_by_test
        for r in (get_latest_by_test() or [])[:12]:
            labs.append({
                'name': (r.get('name') or r.get('lab_key') or '').strip(),
                'value': r.get('value'),
                'unit': (r.get('unit') or '').strip(),
                'date': r.get('date_key') or '',
                'status': r.get('status') or '',
            })
    except Exception:
        labs = []

    # Vaccines on record — name, last dose date, dose count.
    vaccines = []
    try:
        from .immunizations import get_record
        for v in (get_record().get('vaccines') or []):
            vaccines.append({'name': v.get('name') or v.get('key') or '',
                             'last_date': v.get('last_date') or '',
                             'dose_count': v.get('dose_count') or len(v.get('doses') or [])})
    except Exception:
        vaccines = []

    # Dental & vision — next checkups the user noted + their current Rx.
    # The Rx is projected to just the optical fields (no internal id/user_id/
    # created_at need leave the server in the binder JSON).
    dental_vision = {'due': [], 'rx': None}
    try:
        from .dental_vision import get_due, latest_rx
        dental_vision['due'] = get_due() or []
        rx = latest_rx()
        if rx:
            dental_vision['rx'] = {k: rx.get(k) for k in
                ('kind', 'rx_date', 'right_sph', 'right_cyl', 'right_axis', 'right_add',
                 'left_sph', 'left_cyl', 'left_axis', 'left_add', 'pd')}
    except Exception:
        pass

    return {
        'identity': hid.get('identity', {}),
        'blood_type': hid.get('blood_type', ''),
        'advance_care': hid.get('advance_care', {}),
        'allergy_list': hid.get('allergy_list', []),
        'allergies_text': hid.get('allergies', ''),
        'conditions': hid.get('conditions', ''),
        'active_medicines': hid.get('active_medicines', []),
        'notes_medications': hid.get('notes_medications', ''),
        'contacts': hid.get('contacts', []),
        'insurance': hid.get('insurance', {}),
        'labs': labs,
        'vaccines': vaccines,
        'dental_vision': dental_vision,
        'generated': dt.date.today().isoformat(),
    }
