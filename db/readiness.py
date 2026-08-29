"""
db/readiness.py — what this server can actually do, and what it silently cannot.

Arogo is built to self-host, which means the person running it is also the
person who has to notice that it is half-configured. Nothing on any screen said
so. Verification emails have printed to stderr since the first commit; the
person waiting for one sees a page that says "check your inbox" and an inbox
that stays empty, and there is no way for them to find out why from inside the
app. Same for a caregiver SOS that reaches nobody, a push reminder that never
fires, and a backup directory that is not writable.

The pattern in every one of those is the same, and it is deliberate: an
unconfigured integration falls back to printing to stderr and returning True,
so development works without accounts. That is the right default and it is not
changing. What was missing is the other half — one place that says which of
those fallbacks are currently in force, and what each one costs.

So the rule for this file: a check reports, it never fixes. It reads config and
the filesystem and says what is true. Nothing here writes, sends, or repairs.

Each check declares:
    key      stable id
    name     what a person calls it
    kind     'core' (health data is at risk) or 'feature' (something is off)
    check()  -> (status, detail)  where status is ok | off | degraded
    cost     what it means for a real person when this is not configured
    fix      the concrete thing to do about it

A `detail` is a (template, args) pair, not a finished sentence — the same %1
convention tformat() uses on the client. Almost every detail here is prose with
a value in it ("2 kept, newest 3 hours ago"), and a server that formats the
sentence hands the client something it cannot translate. Splitting them keeps
the whole page translatable while the values stay values. Use detail() to build
one; a bare string is allowed only where the text IS data (a hostname, a port).

CHECKS is a registry, and tests/test_readiness.py fails the build if an entry is
missing a field or if a check raises. A report that crashes on one bad check is
worse than no report: it is the moment you most need the other nine.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

# A backup older than this is stale enough to say so. Matches db/backups.py
# rather than guessing separately — two different definitions of "old backup"
# on two screens is how people stop believing either.
from db.backups import STALE_AFTER_HOURS

# Under this, SQLite writes start failing — which in this app means a logged
# dose quietly not saving. Chosen to leave room to notice before that happens.
LOW_DISK_MB = 500

OK, OFF, DEGRADED = 'ok', 'off', 'degraded'


def detail(template, *args):
    """A translatable detail line: an English template plus its values.

    The template is the translation key, so it must be a fixed string — never
    an f-string. Anything variable goes in args and is substituted after
    translation, exactly as tformat() does everywhere else in the app.

    Validated here rather than only in a test. Each check has several branches
    and only the one matching the live environment ever runs, so a test that
    calls the check catches a broken template in one branch out of five — a
    deliberately broken "%3 with two values" went green exactly that way. This
    fires on whichever branch actually executes, in tests and in production
    alike, and report() turns it into one degraded row rather than a 500.
    """
    slots = sorted({int(m) for m in re.findall(r'%(\d)', template)})
    if slots != list(range(1, len(args) + 1)):
        raise ValueError(
            f'detail({template!r}) has slots {slots} but {len(args)} values — '
            f'a missing value prints a literal %n, a spare one is dropped')
    return {'text': template, 'args': [str(a) for a in args]}


# ── Individual checks ───────────────────────────────────────────────────────
# Each returns (status, detail). The detail says what IS true; the cost line
# says what is wrong. None means there is nothing useful to add.

def _check_email():
    import mailer
    if not mailer.is_configured():
        return OFF, None
    where = f'{mailer.SMTP_HOST}:{mailer.SMTP_PORT}'
    if not mailer.SMTP_TLS:
        return DEGRADED, detail('%1 (no STARTTLS)', where)
    return OK, detail('%1', where)


def _check_sms():
    import sms
    if not sms.is_configured('sms'):
        return OFF, None
    return OK, (detail('%1', sms.SMS_FROM) if sms.SMS_FROM else None)


def _check_whatsapp():
    import sms
    if not sms.is_configured('whatsapp'):
        return OFF, None
    return OK, (detail('%1', sms.WHATSAPP_FROM) if sms.WHATSAPP_FROM else None)


def _check_push():
    """Web push needs the pywebpush/py_vapid libraries AND a key.

    The key generates itself on first use, so the interesting failure is the
    library being absent — which is silent: subscriptions save, reminders are
    scheduled, and nothing is ever delivered.
    """
    try:
        import pywebpush  # noqa: F401
        import py_vapid   # noqa: F401
    except ImportError:
        return OFF, detail('%1 is not installed', 'pywebpush')
    try:
        from push import _private_pem
        return (OK, None) if _private_pem() else (OFF, detail('no VAPID key'))
    except Exception as e:
        return DEGRADED, detail('%1', str(e)[:80])


def _check_backups():
    """Writable directory first, then whether anything recent is in it.

    Split deliberately: "no backups yet" on a fresh install is fine, but a
    directory that cannot be written to is the same state and a very different
    problem. Reporting them identically is how the second one hides.
    """
    import time
    from db.backups import backup_dir, _files
    d = backup_dir()
    if not os.path.isdir(d):
        return OFF, detail('%1 does not exist', d)
    if not os.access(d, os.W_OK):
        return DEGRADED, detail('%1 is not writable', d)
    files = _files()
    if not files:
        return DEGRADED, detail('%1 — no backups yet', d)
    age_h = (time.time() - files[0]['mtime']) / 3600
    # Three whole templates rather than one sentence with an age phrase pushed
    # into it. Splicing a finished "3 hours ago" into "%1 kept, newest %2" is
    # the glued-fragment bug: the translator gets half a sentence and cannot
    # reorder across the seam. Each form is translated as the sentence it is.
    n = len(files)
    hours, days = round(age_h), round(age_h / 24)
    if age_h < 1:
        d2 = detail('%1 kept, newest under an hour ago', n)
    elif hours == 1:
        d2 = detail('%1 kept, newest an hour ago', n)
    elif age_h < 48:
        d2 = detail('%1 kept, newest %2 hours ago', n, hours)
    elif days == 1:
        d2 = detail('%1 kept, newest a day ago', n)
    else:
        d2 = detail('%1 kept, newest %2 days ago', n, days)
    return (DEGRADED, d2) if age_h > STALE_AFTER_HOURS else (OK, d2)


def _check_ocr():
    """Reading a prescription photo needs the tesseract binary, not just the
    Python wrapper — the wrapper imports fine and then fails per-request."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return OFF, detail('%1 is not installed', 'pytesseract')
    if not shutil.which('tesseract'):
        return OFF, detail('the tesseract binary is not on PATH')
    return OK, None


def _check_qr():
    try:
        import segno  # noqa: F401
        return OK, None
    except ImportError:
        return OFF, detail('%1 is not installed', 'segno')


def _check_https():
    """COOKIE_SECURE is the honest signal here.

    The app cannot see whether a reverse proxy in front of it terminates TLS,
    so it reports the setting rather than guessing at the deployment. In debug
    it defaults off, which is correct locally and wrong anywhere else.
    """
    import auth
    if auth.COOKIE_SECURE:
        return OK, detail('cookies marked Secure, HSTS on')
    if auth._IS_DEBUG:
        return DEGRADED, detail('debug mode — fine locally, not for a real install')
    return OFF, detail('COOKIE_SECURE=0 with debug off')


def _check_secret_key():
    from config import Config
    key = getattr(Config, 'SECRET_KEY', '')
    if not key or key == 'dev-secret-change-in-production':
        return OFF, detail('still the shipped default')
    # The LENGTH is reported, never the key. See the leak test.
    return (OK, None) if len(key) >= 32 else (DEGRADED, detail('only %1 characters', len(key)))


def _check_debug():
    """Not a missing feature — an actively dangerous setting, reported as one."""
    import auth
    return (DEGRADED, detail('tracebacks are shown to the browser')) if auth._IS_DEBUG \
        else (OK, None)


def _check_disk():
    from db.core import ROOT_DIR
    try:
        free_mb = shutil.disk_usage(ROOT_DIR).free / (1024 * 1024)
    except OSError as e:
        return DEGRADED, detail('%1', str(e)[:80])
    d = (detail('%1 GB free', f'{free_mb / 1024:.1f}') if free_mb >= 1024
         else detail('%1 MB free', f'{free_mb:.0f}'))
    return (DEGRADED, d) if free_mb < LOW_DISK_MB else (OK, d)


def _check_database():
    from db.core import DATABASE_URL, DB_PATH
    if DATABASE_URL:
        return OK, detail('PostgreSQL')
    if not os.path.exists(DB_PATH):
        return DEGRADED, detail('SQLite — file not created yet')
    mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    return OK, detail('SQLite, %1 MB', f'{mb:.0f}')


# ── The registry ────────────────────────────────────────────────────────────
# Ordered by what hurts most when it is wrong, not alphabetically: someone
# skimming this page should hit the things that lose data before the things
# that merely switch a feature off.

CHECKS = [
    {
        'key': 'secret_key', 'name': 'Session secret', 'kind': 'core',
        'check': _check_secret_key,
        'cost': 'Everyone is signed out whenever the server restarts, and the '
                'shipped default is public — anyone who knows it can forge a '
                'session cookie for any account on this install.',
        'fix': 'Set SECRET_KEY to a random 64-character value: '
               'python -c "import secrets; print(secrets.token_hex(32))"',
    },
    {
        'key': 'https', 'name': 'HTTPS and secure cookies', 'kind': 'core',
        'check': _check_https,
        'cost': 'Session cookies travel in the clear, so anyone on the same '
                'network can read them and sign in as that person — with '
                'access to their medicines, doses and records.',
        'fix': 'Serve over TLS and set COOKIE_SECURE=1. This also turns on '
               'HSTS. Arogo cannot detect a TLS-terminating proxy, so this '
               'reflects the setting, not the deployment.',
    },
    {
        'key': 'debug', 'name': 'Debug mode', 'kind': 'core',
        'check': _check_debug,
        'cost': 'An error shows a full traceback in the browser, including file '
                'paths and the values being handled — which here means health '
                'data on an error page.',
        'fix': 'Set FLASK_DEBUG=0. The app refuses to start without a real '
               'SECRET_KEY once you do.',
    },
    {
        'key': 'backups', 'name': 'Backups', 'kind': 'core',
        'check': _check_backups,
        'cost': 'There is nothing to restore from. On a Pi the SD card is the '
                'single most likely thing to fail, and it takes every dose, '
                'reading and record with it.',
        'fix': 'Make BACKUP_DIR writable (defaults to ./backups) and run the '
               'scheduler, which keeps 14 rolling copies and verifies each one.',
    },
    {
        'key': 'disk', 'name': 'Disk space', 'kind': 'core',
        'check': _check_disk,
        'cost': 'When the disk fills, SQLite writes start failing. In this app '
                'that is a logged dose quietly not saving, while the person is '
                'holding the pill.',
        'fix': f'Keep at least {LOW_DISK_MB} MB free. Storage above shows what '
               f'uploads are using, and old backups can be pruned.',
    },
    {
        'key': 'database', 'name': 'Database', 'kind': 'core',
        'check': _check_database,
        'cost': 'No database means no app at all — this reports which one is in '
                'use so a surprise is caught before it matters.',
        'fix': 'Set DATABASE_URL for PostgreSQL, or leave it unset for SQLite.',
    },
    {
        'key': 'email', 'name': 'Email', 'kind': 'feature',
        'check': _check_email,
        'cost': 'Verification links and password resets are printed to the '
                'server log instead of sent. Someone who signs up sees "check '
                'your inbox" and waits for an email that will never arrive, '
                'and someone locked out cannot get back in without you.',
        'fix': 'Set SMTP_HOST, SMTP_USER, SMTP_PASS and APP_BASE_URL. See '
               '.env.example.',
    },
    {
        'key': 'push', 'name': 'Push reminders', 'kind': 'feature',
        'check': _check_push,
        'cost': 'Dose reminders are scheduled and never delivered. The app '
                'shows them as set up, so a missed dose looks like the person '
                'ignored a reminder they were never actually sent.',
        'fix': 'pip install -r requirements.txt (pywebpush). The VAPID key '
               'generates itself on first use.',
    },
    {
        'key': 'sms', 'name': 'Caregiver SMS', 'kind': 'feature',
        'check': _check_sms,
        'cost': 'An emergency SOS and the missed-dose escalation reach nobody. '
                'They are written to the server log and the sender is told '
                'they were sent.',
        'fix': 'Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_SMS_FROM.',
    },
    {
        'key': 'whatsapp', 'name': 'Caregiver WhatsApp', 'kind': 'feature',
        'check': _check_whatsapp,
        'cost': 'The WhatsApp route for caregiver alerts is unavailable. SMS is '
                'used instead where it is configured.',
        'fix': 'Set TWILIO_WHATSAPP_FROM alongside the Twilio credentials.',
    },
    {
        'key': 'ocr', 'name': 'Prescription photo reading', 'kind': 'feature',
        'check': _check_ocr,
        'cost': 'Photographed prescriptions and lab reports cannot be read '
                'automatically. Everything still works typed in by hand.',
        'fix': 'apt install tesseract-ocr, then pip install pytesseract.',
    },
    {
        'key': 'qr', 'name': 'Emergency QR code', 'kind': 'feature',
        'check': _check_qr,
        'cost': 'The emergency card cannot render its QR code. The card itself '
                'still prints with the details on it.',
        'fix': 'pip install -r requirements.txt (segno).',
    },
]


def report() -> dict:
    """Run every check. One that raises is reported, never fatal.

    A check calling into an unconfigured integration is exactly where an
    unexpected exception is likely, and losing the whole page to it would hide
    the other eleven answers at the moment they are most wanted.
    """
    items = []
    for c in CHECKS:
        try:
            status, d = c['check']()
        except Exception as e:                       # noqa: BLE001
            status, d = DEGRADED, detail('check failed: %1', str(e)[:100])
        items.append({
            'key': c['key'], 'name': c['name'], 'kind': c['kind'],
            'status': status, 'detail': d,
            'cost': c['cost'], 'fix': c['fix'],
        })
    return {
        'items': items,
        'counts': {s: sum(1 for i in items if i['status'] == s)
                   for s in (OK, DEGRADED, OFF)},
        'core_problems': [i['key'] for i in items
                          if i['kind'] == 'core' and i['status'] != OK],
        'python': sys.version.split()[0],
    }
