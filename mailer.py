"""
mailer.py — Outbound email for Arogo.

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
SMTP_FROM = os.environ.get('SMTP_FROM', SMTP_USER or 'arogo@localhost')
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
        'Verify your Arogo email',
        'Welcome to Arogo!\n\n'
        'Confirm your email address by opening this link (valid for 24 hours):\n\n'
        f'    {link}\n\n'
        "If you didn't create an Arogo account, you can ignore this email.\n",
    )


def send_weekly_digest_email(to: str, name: str, digest: dict, unsub_url: str) -> bool:
    lines = [
        f"Hi {name or 'there'},",
        '',
        digest['headline'],
        f"Your week: {digest['period_label']}  ·  Overall score {digest['overall_score']}/100",
        '',
    ]
    if digest.get('highlights'):
        lines.append('At a glance:')
        lines += [f"  {h['icon']} {h['label']}: {h['value']}" for h in digest['highlights']]
        lines.append('')
    if digest.get('wins'):
        lines.append('Wins:')
        lines += [f"  {w['icon']} {w['text']}" for w in digest['wins']]
        lines.append('')
    if digest.get('concerns'):
        lines.append('Worth watching:')
        lines += [f"  {c['icon']} {c['text']}" for c in digest['concerns']]
        lines.append('')
    lines += [
        f'Open Arogo: {APP_BASE_URL}/',
        '',
        f'No longer want these? Unsubscribe: {unsub_url}',
    ]
    return send_email(to, f"Your Arogo week — {digest['period_label']}", '\n'.join(lines) + '\n')


def send_caregiver_digest_email(to: str, name: str, digest: dict, unsub_url: str) -> bool:
    lines = [
        f"Hi {name or 'there'},",
        '',
        f"Here's how your family did this week ({digest['period_label']}):",
        '',
    ]
    for m in digest.get('members', []):
        if m['total']:
            adh = f"{round(m['adherence_pct'] or 0)}% of doses taken ({m['taken']}/{m['total']})"
        else:
            adh = "no scheduled doses this week"
        extras = []
        if m.get('sleep_avg'):
            extras.append(f"{m['sleep_avg']}h avg sleep")
        if m.get('symptoms'):
            extras.append(f"{m['symptoms']} symptom log{'s' if m['symptoms'] != 1 else ''}")
        line = f"  • {m['name']}: {adh}"
        if extras:
            line += "  ·  " + ", ".join(extras)
        lines.append(line)
    lines += [
        '',
        'These are the family members who share their medicines with you.',
        f'Open Arogo: {APP_BASE_URL}/',
        '',
        f'No longer want these? Unsubscribe: {unsub_url}',
    ]
    return send_email(to, f"Your family's week on Arogo — {digest['period_label']}",
                      '\n'.join(lines) + '\n')


def send_family_invite_email(to: str, token: str, inviter: str, group: str) -> bool:
    link = f'{APP_BASE_URL}/?family_invite={token}'
    return send_email(
        to,
        f'{inviter} invited you to their Arogo family group',
        f'{inviter} invited you to join the family group "{group}" on Arogo.\n\n'
        'Family members choose exactly which health categories they share —\n'
        'nothing is visible unless you turn it on.\n\n'
        'Open this link to join (valid for 72 hours):\n\n'
        f'    {link}\n\n'
        "If you don't want to join, just ignore this email.\n",
    )


def send_password_reset_email(to: str, token: str) -> bool:
    link = f'{APP_BASE_URL}/?reset={token}'
    return send_email(
        to,
        'Reset your Arogo password',
        'Someone requested a password reset for your Arogo account.\n\n'
        'Open this link to choose a new password (valid for 1 hour):\n\n'
        f'    {link}\n\n'
        "If this wasn't you, ignore this email — your password is unchanged.\n",
    )
