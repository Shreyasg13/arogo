"""
mailer.py — Outbound email for MedEasy Health OS.

Pure stdlib (smtplib + email.message), configured entirely via environment:

    SMTP_HOST      e.g. smtp.gmail.com  (unset → dev mode, emails logged to stderr)
    SMTP_PORT      default 587
    SMTP_USER      SMTP login
    SMTP_PASS      SMTP password / app password
    SMTP_FROM      From address (defaults to SMTP_USER)
    SMTP_TLS       '1' (default) = STARTTLS, '0' = plain
    APP_BASE_URL   public URL used in email links, default http://localhost:5000

Dev mode keeps the old behaviour: the full email (including links) is printed
to stderr so flows can be exercised without an SMTP account.
"""
from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage

SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
SMTP_FROM = os.environ.get('SMTP_FROM', SMTP_USER or 'medeasy@localhost')
SMTP_TLS  = os.environ.get('SMTP_TLS', '1') == '1'
APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:5000').rstrip('/')


def is_configured() -> bool:
    return bool(SMTP_HOST)


def send_email(to: str, subject: str, text: str) -> bool:
    """Send a plain-text email. Returns True if handed to the SMTP server.

    Unconfigured (no SMTP_HOST): logs the email to stderr and returns True so
    dev flows keep working without an SMTP account.
    """
    if not is_configured():
        print(f'[MAIL:dev] To: {to}\n[MAIL:dev] Subject: {subject}\n'
              f'[MAIL:dev] {text}', file=sys.stderr)
        return True
    try:
        msg = EmailMessage()
        msg['From']    = SMTP_FROM
        msg['To']      = to
        msg['Subject'] = subject
        msg.set_content(text)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            if SMTP_TLS:
                s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f'[MAIL] Send to {to} failed: {e}', file=sys.stderr)
        return False


def send_verification_email(to: str, token: str) -> bool:
    link = f'{APP_BASE_URL}/auth/verify/{token}'
    return send_email(
        to,
        'Verify your MedEasy email',
        'Welcome to MedEasy!\n\n'
        'Confirm your email address by opening this link (valid for 24 hours):\n\n'
        f'    {link}\n\n'
        "If you didn't create a MedEasy account, you can ignore this email.\n",
    )


def send_password_reset_email(to: str, token: str) -> bool:
    link = f'{APP_BASE_URL}/?reset={token}'
    return send_email(
        to,
        'Reset your MedEasy password',
        'Someone requested a password reset for your MedEasy account.\n\n'
        'Open this link to choose a new password (valid for 1 hour):\n\n'
        f'    {link}\n\n'
        "If this wasn't you, ignore this email — your password is unchanged.\n",
    )
