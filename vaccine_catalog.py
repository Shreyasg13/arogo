"""
vaccine_catalog.py — a curated catalog of vaccines, weighted to India's
Universal Immunization Programme (UIP) + IAP schedule, plus common adult,
travel, and optional vaccines.

HONESTY NOTE: the `when` text is general guidance, not a personal schedule — the
right timing depends on age, health, pregnancy, and local programme, and a
doctor's advice always wins. The app tracks what you've had and, for the few
vaccines that genuinely recur on a fixed interval (tetanus, flu, typhoid),
estimates when the next is due — always framed as an estimate.
"""

CATALOG = [
    # ── Childhood (UIP / IAP) ───────────────────────────────────────────
    {'key': 'bcg',          'name': 'BCG',                         'category': 'Childhood', 'when': 'At birth'},
    {'key': 'opv',          'name': 'OPV (Oral Polio)',            'category': 'Childhood', 'when': 'Birth, 6 / 10 / 14 weeks, boosters'},
    {'key': 'hepb',         'name': 'Hepatitis B',                 'category': 'Childhood', 'when': 'Birth, 6 / 10 / 14 weeks'},
    {'key': 'penta',        'name': 'Pentavalent (DPT-HepB-Hib)',  'category': 'Childhood', 'when': '6 / 10 / 14 weeks'},
    {'key': 'rota',         'name': 'Rotavirus',                   'category': 'Childhood', 'when': '6 / 10 / 14 weeks'},
    {'key': 'pcv',          'name': 'PCV (Pneumococcal)',          'category': 'Childhood', 'when': '6 & 14 weeks, 9 months'},
    {'key': 'ipv',          'name': 'IPV (Injectable Polio)',      'category': 'Childhood', 'when': '6 & 14 weeks'},
    {'key': 'mr',           'name': 'Measles-Rubella (MR)',        'category': 'Childhood', 'when': '9–12 months & 16–24 months'},
    {'key': 'je',           'name': 'Japanese Encephalitis',       'category': 'Childhood', 'when': '9 months & 16–24 months (endemic areas)'},
    {'key': 'dpt_booster',  'name': 'DPT booster',                 'category': 'Childhood', 'when': '16–24 months & 5–6 years'},

    # ── Adult / recurring ───────────────────────────────────────────────
    {'key': 'td',           'name': 'Td / Tdap (Tetanus)',         'category': 'Adult', 'when': 'Every 10 years', 'interval_days': 3650},
    {'key': 'influenza',    'name': 'Influenza (Flu)',             'category': 'Adult', 'when': 'Every year',     'interval_days': 365},
    {'key': 'covid',        'name': 'COVID-19',                    'category': 'Adult', 'when': 'Per current guidance'},
    {'key': 'pneumo_adult', 'name': 'Pneumococcal (adult)',        'category': 'Adult', 'when': '65+ or high-risk'},

    # ── Optional / catch-up ─────────────────────────────────────────────
    {'key': 'mmr',          'name': 'MMR',                         'category': 'Optional', 'when': 'Childhood or catch-up'},
    {'key': 'varicella',    'name': 'Varicella (Chickenpox)',      'category': 'Optional', 'when': '2 doses'},
    {'key': 'hepa',         'name': 'Hepatitis A',                 'category': 'Optional', 'when': '2 doses'},
    {'key': 'hpv',          'name': 'HPV',                         'category': 'Optional', 'when': '9–14 yr (2 doses) or 15+ (3 doses)'},

    # ── Travel ──────────────────────────────────────────────────────────
    {'key': 'typhoid',      'name': 'Typhoid',                     'category': 'Travel', 'when': 'Every 3 years', 'interval_days': 1095},
    {'key': 'rabies',       'name': 'Rabies',                      'category': 'Travel', 'when': 'Pre-exposure or post-bite'},
    {'key': 'yellow_fever', 'name': 'Yellow Fever',                'category': 'Travel', 'when': 'Once (required for some countries)'},
]

_BY_KEY = {v['key']: v for v in CATALOG}


def get_vaccine(key):
    return _BY_KEY.get(key)


def categories():
    seen, out = set(), []
    for v in CATALOG:
        if v['category'] not in seen:
            seen.add(v['category'])
            out.append(v['category'])
    return out


def search(q, limit=10):
    q = (q or '').strip().lower()
    if not q:
        return CATALOG[:limit]
    return [v for v in CATALOG if q in v['name'].lower() or q in v['key']][:limit]
