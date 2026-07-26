"""
sms.py — Outbound SMS / WhatsApp for Arogo, so a caregiver can be alerted
WITHOUT installing the app or creating an account.

Pure stdlib (urllib), configured entirely via environment — a deliberate mirror
of mailer.py, including its dev-mode behaviour:

    TWILIO_ACCOUNT_SID    Twilio account SID   (unset → dev mode, logged to stderr)
    TWILIO_AUTH_TOKEN     Twilio auth token
    TWILIO_SMS_FROM       sender number in E.164, e.g. +14155552671
    TWILIO_WHATSAPP_FROM  WhatsApp sender in E.164 (the 'whatsapp:' prefix is added)

Dev mode (no credentials) prints the message to stderr and returns True, so the
escalation ladder can be exercised without a Twilio account. Callers that need
to know whether a *human* was actually reached must gate on is_configured(),
exactly as the caregiver-alert scheduler does for email — a dev-mode "True"
means "logged", not "delivered".
"""
from __future__ import annotations

import base64
import os
import sys
import urllib.parse
import urllib.request

TWILIO_SID   = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
SMS_FROM     = os.environ.get('TWILIO_SMS_FROM', '')
WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', '')

_API = 'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'


def is_configured(channel: str = 'sms') -> bool:
    """True only when this channel can actually deliver a message."""
    if not (TWILIO_SID and TWILIO_TOKEN):
        return False
    if channel == 'whatsapp':
        return bool(WHATSAPP_FROM)
    return bool(SMS_FROM)


def _twilio_payload(to: str, text: str, channel: str) -> dict:
    """Build the Twilio Messages form fields (separated out for testing)."""
    if channel == 'whatsapp':
        return {'To': f'whatsapp:{to}', 'From': f'whatsapp:{WHATSAPP_FROM}', 'Body': text}
    return {'To': to, 'From': SMS_FROM, 'Body': text}


def _send(to: str, text: str, channel: str) -> bool:
    tag = 'WA' if channel == 'whatsapp' else 'SMS'
    if not is_configured(channel):
        print(f'[{tag}:dev] To: {to}\n[{tag}:dev] {text}', file=sys.stderr)
        return True
    try:
        data = urllib.parse.urlencode(_twilio_payload(to, text, channel)).encode()
        url = _API.format(sid=urllib.parse.quote(TWILIO_SID))
        req = urllib.request.Request(url, data=data, method='POST')
        auth = base64.b64encode(f'{TWILIO_SID}:{TWILIO_TOKEN}'.encode()).decode()
        req.add_header('Authorization', f'Basic {auth}')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f'[{tag}] Send to {to} failed: {e}', file=sys.stderr)
        return False


def send_sms(to: str, text: str) -> bool:
    """Send an SMS. Returns True if handed to Twilio (or logged in dev mode)."""
    return _send(to, text, 'sms')


def send_whatsapp(to: str, text: str) -> bool:
    """Send a WhatsApp message. Returns True if handed to Twilio (or logged)."""
    return _send(to, text, 'whatsapp')


def notify_contact(contact: dict, text: str) -> bool:
    """Message an account-less caregiver contact over their chosen channel.

    `contact` is a caregiver_contacts row: {phone, channel, ...}.
    """
    phone = (contact.get('phone') or '').strip()
    if not phone:
        return False
    if contact.get('channel') == 'whatsapp':
        return send_whatsapp(phone, text)
    return send_sms(phone, text)
