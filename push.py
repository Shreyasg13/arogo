"""
push.py — Web Push notifications via pywebpush (optional dependency).

If pywebpush isn't installed, PUSH_AVAILABLE is False and every entry
point degrades to a no-op — the app runs fine without push.

VAPID keys: set VAPID_PRIVATE_KEY (PEM) + VAPID_CLAIMS_EMAIL in env for
production; otherwise a keypair is generated once and stored in the
app_config table so all workers share it.
"""
from __future__ import annotations

import json
import os
import sys

try:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid02, b64urlencode
    from cryptography.hazmat.primitives import serialization
    PUSH_AVAILABLE = True
except ImportError:
    PUSH_AVAILABLE = False

VAPID_CLAIMS_EMAIL = os.environ.get('VAPID_CLAIMS_EMAIL', 'mailto:admin@medeasy.local')


def _get_config(key: str):
    from db.core import execute
    r = execute("SELECT value FROM app_config WHERE key=?", (key,), fetchone=True)
    return r['value'] if r else None


def _set_config(key: str, value: str):
    from db.core import execute
    execute("DELETE FROM app_config WHERE key=?", (key,), commit=True)
    execute("INSERT INTO app_config (key, value) VALUES (?, ?)", (key, value), commit=True)


def _private_pem() -> str | None:
    """VAPID private key: env override, else generated once into app_config."""
    if not PUSH_AVAILABLE:
        return None
    pem = os.environ.get('VAPID_PRIVATE_KEY') or _get_config('vapid_private_pem')
    if not pem:
        v = Vapid02()
        v.generate_keys()
        pem = v.private_pem().decode()
        _set_config('vapid_private_pem', pem)
    return pem


def get_public_key() -> str | None:
    """applicationServerKey for the browser (b64url uncompressed EC point)."""
    if not PUSH_AVAILABLE:
        return None
    pem = _private_pem()
    v = Vapid02.from_pem(pem.encode())
    raw = v.public_key.public_bytes(serialization.Encoding.X962,
                                    serialization.PublicFormat.UncompressedPoint)
    return b64urlencode(raw)


def send_push(sub_row: dict, title: str, body: str, url: str = '/',
              actions: list | None = None) -> bool:
    """Send one notification; drops the subscription if the browser revoked it.

    `actions` are Web Push notification buttons, e.g.
        [{'action': 'water-250', 'title': '💧 250ml'}, {'action': 'snooze', ...}]
    The service worker renders them and handles the tap — letting the user act
    (e.g. log water) without ever opening the app. Max 2 render on most browsers.
    """
    if not PUSH_AVAILABLE:
        return False
    from db.core import execute
    payload = {'title': title, 'body': body, 'url': url}
    if actions:
        payload['actions'] = actions
    try:
        webpush(
            subscription_info=json.loads(sub_row['sub_json']),
            data=json.dumps(payload),
            vapid_private_key=_private_pem(),
            vapid_claims={'sub': VAPID_CLAIMS_EMAIL},
        )
        return True
    except WebPushException as e:
        status = getattr(getattr(e, 'response', None), 'status_code', None)
        if status in (404, 410):   # endpoint gone — browser unsubscribed
            execute("DELETE FROM push_subscriptions WHERE id=?", (sub_row['id'],), commit=True)
        else:
            print(f'[push] send failed ({status}): {e}', file=sys.stderr)
        return False
    except Exception as e:
        print(f'[push] send error: {e}', file=sys.stderr)
        return False


def push_to_user(user_id: str, title: str, body: str, url: str = '/',
                 actions: list | None = None) -> int:
    """Send to every subscription the user has. Returns delivered count."""
    if not PUSH_AVAILABLE:
        return 0
    from db.core import execute
    subs = execute("SELECT * FROM push_subscriptions WHERE user_id=?",
                   (user_id,), fetchall=True)
    return sum(1 for s in subs if send_push(s, title, body, url, actions))
