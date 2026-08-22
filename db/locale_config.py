"""
db/locale_config.py — the user's country → currency + financial-year rules.

The app was India-first; this makes country a per-user choice so currency,
number formatting, and the medical-spend financial year adapt instead of being
hard-coded to ₹ / April–March. Country lives on the user profile; India stays
the default so nothing changes for existing users until they pick another.

Nothing here is advice — the financial-year boundary just decides how a
"medical spend by year" summary is grouped; tax eligibility is never asserted.
"""
from __future__ import annotations

DEFAULT_COUNTRY = 'IN'

# code → name, currency code, symbol, number locale, financial-year START month
# (1 = calendar Jan–Dec), and an optional country-specific note for the spend
# organiser (only India references a scheme by name).
COUNTRIES = {
    'IN': {'name': 'India',              'currency': 'INR', 'symbol': '₹',  'locale': 'en-IN', 'fy_start_month': 4, 'tax_note': 'e.g. Section 80D'},
    'US': {'name': 'United States',      'currency': 'USD', 'symbol': '$',  'locale': 'en-US', 'fy_start_month': 1, 'tax_note': ''},
    'GB': {'name': 'United Kingdom',     'currency': 'GBP', 'symbol': '£',  'locale': 'en-GB', 'fy_start_month': 4, 'tax_note': ''},
    'CA': {'name': 'Canada',             'currency': 'CAD', 'symbol': '$',  'locale': 'en-CA', 'fy_start_month': 1, 'tax_note': ''},
    'AU': {'name': 'Australia',          'currency': 'AUD', 'symbol': '$',  'locale': 'en-AU', 'fy_start_month': 7, 'tax_note': ''},
    'NZ': {'name': 'New Zealand',        'currency': 'NZD', 'symbol': '$',  'locale': 'en-NZ', 'fy_start_month': 4, 'tax_note': ''},
    'AE': {'name': 'United Arab Emirates', 'currency': 'AED', 'symbol': 'د.إ', 'locale': 'en-AE', 'fy_start_month': 1, 'tax_note': ''},
    'SG': {'name': 'Singapore',          'currency': 'SGD', 'symbol': '$',  'locale': 'en-SG', 'fy_start_month': 1, 'tax_note': ''},
    'ZA': {'name': 'South Africa',       'currency': 'ZAR', 'symbol': 'R',  'locale': 'en-ZA', 'fy_start_month': 3, 'tax_note': ''},
    'JP': {'name': 'Japan',              'currency': 'JPY', 'symbol': '¥',  'locale': 'ja-JP', 'fy_start_month': 4, 'tax_note': ''},
    'CN': {'name': 'China',              'currency': 'CNY', 'symbol': '¥',  'locale': 'zh-CN', 'fy_start_month': 1, 'tax_note': ''},
    'DE': {'name': 'Germany',            'currency': 'EUR', 'symbol': '€',  'locale': 'de-DE', 'fy_start_month': 1, 'tax_note': ''},
    'FR': {'name': 'France',             'currency': 'EUR', 'symbol': '€',  'locale': 'fr-FR', 'fy_start_month': 1, 'tax_note': ''},
    'ES': {'name': 'Spain',              'currency': 'EUR', 'symbol': '€',  'locale': 'es-ES', 'fy_start_month': 1, 'tax_note': ''},
    'IT': {'name': 'Italy',              'currency': 'EUR', 'symbol': '€',  'locale': 'it-IT', 'fy_start_month': 1, 'tax_note': ''},
    'NL': {'name': 'Netherlands',        'currency': 'EUR', 'symbol': '€',  'locale': 'nl-NL', 'fy_start_month': 1, 'tax_note': ''},
    'IE': {'name': 'Ireland',            'currency': 'EUR', 'symbol': '€',  'locale': 'en-IE', 'fy_start_month': 1, 'tax_note': ''},
    'BR': {'name': 'Brazil',             'currency': 'BRL', 'symbol': 'R$', 'locale': 'pt-BR', 'fy_start_month': 1, 'tax_note': ''},
    'MX': {'name': 'Mexico',             'currency': 'MXN', 'symbol': '$',  'locale': 'es-MX', 'fy_start_month': 1, 'tax_note': ''},
    'PK': {'name': 'Pakistan',           'currency': 'PKR', 'symbol': '₨',  'locale': 'en-PK', 'fy_start_month': 7, 'tax_note': ''},
    'BD': {'name': 'Bangladesh',         'currency': 'BDT', 'symbol': '৳',  'locale': 'en-BD', 'fy_start_month': 7, 'tax_note': ''},
    'LK': {'name': 'Sri Lanka',          'currency': 'LKR', 'symbol': '₨',  'locale': 'en-LK', 'fy_start_month': 4, 'tax_note': ''},
    'NP': {'name': 'Nepal',              'currency': 'NPR', 'symbol': 'रू', 'locale': 'en-IN', 'fy_start_month': 4, 'tax_note': ''},
    'OT': {'name': 'Other',              'currency': 'USD', 'symbol': '$',  'locale': 'en-US', 'fy_start_month': 1, 'tax_note': ''},
}


def valid_country(code):
    code = str(code or '').strip().upper()
    return code if code in COUNTRIES else None


def country_of(profile=None):
    """The calling user's country code, defaulting to India. Pass a profile dict
    to avoid a re-query."""
    if profile is None:
        try:
            from .food import get_profile
            profile = get_profile() or {}
        except Exception:
            profile = {}
    return valid_country(profile.get('country')) or DEFAULT_COUNTRY


def currency_of(country=None, profile=None):
    c = COUNTRIES[country_of(profile) if country is None else (valid_country(country) or DEFAULT_COUNTRY)]
    return {'code': c['currency'], 'symbol': c['symbol'], 'locale': c['locale']}


def country_info(country=None):
    """Full config for a country; with no argument, the calling user's country."""
    code = valid_country(country) if country is not None else country_of()
    return COUNTRIES[code or DEFAULT_COUNTRY]


def country_list():
    """For the picker — sorted by name, with India + common ones staying usable."""
    return [{'code': k, 'name': v['name'], 'symbol': v['symbol'], 'currency': v['currency']}
            for k, v in sorted(COUNTRIES.items(), key=lambda kv: (kv[0] == 'OT', kv[1]['name']))]


# ── Units of measurement ────────────────────────────────────────────────────
# Data is always STORED canonically (weight kg, height cm, glucose mg/dL,
# temperature carries its own unit). These are display/input preferences only.
_UNIT_VALUES = {'weight': {'kg', 'lb'}, 'height': {'cm', 'ft'},
                'temp': {'c', 'f'}, 'glucose': {'mgdl', 'mmol'}}
# Country conventions (best-effort defaults the user can override per unit).
_IMPERIAL_WEIGHT = {'US'}
_IMPERIAL_HEIGHT = {'US', 'GB'}
_FAHRENHEIT = {'US'}
_MMOL = {'GB', 'CA', 'AU', 'NZ', 'IE', 'DE', 'FR', 'ES', 'IT', 'NL', 'ZA', 'CN'}


def valid_unit(kind, v):
    v = str(v or '').strip().lower()
    return v if v in _UNIT_VALUES.get(kind, set()) else None


def _country_default_units(code):
    return {
        'weight':  'lb' if code in _IMPERIAL_WEIGHT else 'kg',
        'height':  'ft' if code in _IMPERIAL_HEIGHT else 'cm',
        'temp':    'f'  if code in _FAHRENHEIT else 'c',
        'glucose': 'mmol' if code in _MMOL else 'mgdl',
    }


def units_of(profile=None):
    """The calling user's units — country defaults, overridden by any explicit
    per-unit preference on the profile."""
    if profile is None:
        try:
            from .food import get_profile
            profile = get_profile() or {}
        except Exception:
            profile = {}
    d = _country_default_units(country_of(profile))
    for kind in list(d):
        v = valid_unit(kind, (profile or {}).get(kind + '_unit'))
        if v:
            d[kind] = v
    return d
