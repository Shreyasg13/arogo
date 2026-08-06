"""
db/pharmacy.py — the user's default pharmacy, for one-tap refills.

Just a name + phone stored on the profile, plus a helper that composes a refill
message from the current pill-run list. No auto-sending: the app hands the user a
tel: link and copyable text; the user makes the call.
"""
from __future__ import annotations
import re

from .core import execute, now_iso, current_user_id
from .food import get_profile


def get_pharmacy() -> dict:
    p = get_profile() or {}
    name = (p.get('pharmacy_name') or '').strip()
    phone = (p.get('pharmacy_phone') or '').strip()
    return {'name': name, 'phone': phone, 'has_pharmacy': bool(name or phone)}


def set_pharmacy(name: str, phone: str) -> dict:
    uid = current_user_id()
    get_profile()          # ensure a profile row exists
    name = str(name or '').strip()[:120]
    # Keep only characters a dialer accepts, so the tel: link can't be poisoned.
    phone = re.sub(r'[^0-9+\-() ]', '', str(phone or ''))[:24].strip()
    execute("UPDATE user_profile SET pharmacy_name=?, pharmacy_phone=?, updated_at=? WHERE user_id=?",
            (name, phone, now_iso(), uid), commit=True)
    return get_pharmacy()


def refill_message() -> str:
    """A ready-to-send refill note listing everything on the current pharmacy run.
    Empty string when nothing needs refilling — the caller decides what to show."""
    from .medicines import get_refill_list
    items = get_refill_list() or []
    names = [i['name'] for i in items if i.get('name')]
    if not names:
        return ''
    return 'Hi, I\'d like to refill: ' + ', '.join(names) + '. Thank you.'
