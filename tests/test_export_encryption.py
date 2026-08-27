"""An encrypted export must open without Arogo.

The encryption itself lives in the browser and is tested there. What is tested
HERE is the part that no amount of JavaScript testing can establish: that a file
Arogo wrote can be opened by something that is not Arogo.

That matters more than the cipher does. An export is how someone takes their
data out — to another tool, to a doctor, to whatever exists after this app stops
being maintained. A scheme only Arogo can undo would quietly turn "your data is
yours" into "yours while you keep running our software", which is worse than
leaving the file in plaintext, because it looks like the opposite.

So the test writes a file with the real browser code and opens it with the
standalone script. Neither side is allowed to reimplement the format; if they
ever drift, this fails.
"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

decrypt_export = pytest.importorskip(
    'decrypt_export', reason='scripts/decrypt_export.py must be importable')

NODE = shutil.which('node')
HAVE_CRYPTOGRAPHY = True
try:
    import cryptography  # noqa: F401
except ImportError:
    HAVE_CRYPTOGRAPHY = False


def _encrypt_in_browser_code(plaintext, passphrase):
    """Produce a file using the real static/js/app.js implementation."""
    out = subprocess.run(
        [NODE, os.path.join('tests', 'js', 'encrypt_for_interop.mjs'),
         plaintext, passphrase],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout


needs_node = pytest.mark.skipif(not NODE, reason='node is not installed')
needs_crypto = pytest.mark.skipif(
    not HAVE_CRYPTOGRAPHY, reason='cryptography is not installed')


# ── The claim on the export page ────────────────────────────────────────────

@needs_node
@needs_crypto
def test_python_can_open_what_the_browser_wrote():
    """The whole promise, in one test."""
    secret = json.dumps({'medicines': [{'name': 'Metformin', 'dosage': '500'}],
                         'vitals': [{'type': 'blood_pressure', 'value1': 128}]})
    armoured = _encrypt_in_browser_code(secret, 'a real passphrase 123')
    assert decrypt_export.decrypt(armoured, 'a real passphrase 123') == secret


@needs_node
@needs_crypto
def test_a_wrong_passphrase_fails_the_same_way_on_both_sides():
    armoured = _encrypt_in_browser_code('{"a":1}', 'the-right-one')
    with pytest.raises(ValueError) as e:
        decrypt_export.decrypt(armoured, 'the-wrong-one')
    # And it does NOT claim to know which of the two went wrong, because
    # authenticated encryption cannot tell.
    msg = str(e.value).lower()
    assert 'wrong' in msg and 'altered' in msg


@needs_node
@needs_crypto
def test_a_tampered_file_is_refused_by_the_script_too():
    """Silent corruption of a medical record on the way back in is the worst
    outcome available here, so it has to fail loudly on both sides."""
    armoured = _encrypt_in_browser_code('{"medicines":[]}', 'pw-12345678')
    lines = armoured.split('\n')
    ct = lines[2]
    lines[2] = ('B' if ct[0] == 'A' else 'A') + ct[1:]
    with pytest.raises(ValueError):
        decrypt_export.decrypt('\n'.join(lines), 'pw-12345678')


@needs_node
def test_the_browser_writes_a_header_the_script_understands():
    """No node/cryptography needed on the reading side for this one — it only
    checks the two agree about the format."""
    armoured = _encrypt_in_browser_code('x', 'pw-12345678')
    header, ct = decrypt_export.parse(armoured)
    assert header['kdf'] == decrypt_export.SUPPORTED_KDF
    assert header['cipher'] == decrypt_export.SUPPORTED_CIPHER
    assert header['iterations'] >= 600000
    assert len(base64.b64decode(header['salt'])) == 16
    assert len(base64.b64decode(header['iv'])) == 12
    assert len(ct) > 0


@needs_node
def test_the_encrypted_file_does_not_contain_the_plaintext():
    armoured = _encrypt_in_browser_code('Metformin 500mg twice daily', 'pw-12345678')
    assert 'Metformin' not in armoured
    assert base64.b64encode(b'Metformin 500mg twice daily').decode() not in armoured


# ── The script's own error handling ─────────────────────────────────────────
# These need neither node nor cryptography: they are about what the script says
# when handed the wrong thing, and a confusing message here lands on someone
# trying to open their own medical history.

def test_a_plain_export_is_not_mistaken_for_an_encrypted_one():
    with pytest.raises(ValueError) as e:
        decrypt_export.parse('{"medicines": []}')
    assert 'needs no decrypting' in str(e.value)


def test_a_truncated_file_says_so_rather_than_failing_obscurely():
    with pytest.raises(ValueError) as e:
        decrypt_export.parse('AROGO-ENC1\n')
    assert 'truncated' in str(e.value).lower()


def test_an_unsupported_format_is_refused_not_guessed_at():
    """Guessing surfaces as "wrong passphrase", which sends someone hunting for
    a typo in a passphrase that was correct the whole time."""
    header = json.dumps({'kdf': 'scrypt', 'cipher': 'ChaCha20-Poly1305',
                         'salt': 'AAAA', 'iv': 'AAAA', 'iterations': 1})
    with pytest.raises(ValueError) as e:
        decrypt_export.parse(f'AROGO-ENC1\n{header}\nAAAA')
    msg = str(e.value)
    assert 'scrypt' in msg and 'ChaCha20-Poly1305' in msg
    # It must point at the way out rather than just refusing.
    assert 'header' in msg.lower()


def test_the_script_documents_the_format_in_its_own_docstring():
    """Someone opening this file years from now, with no Arogo to consult, has
    to be able to read the format out of the script itself."""
    doc = decrypt_export.__doc__
    for needed in ('AROGO-ENC1', 'PBKDF2', 'AES-256-GCM', 'salt', 'iv'):
        assert needed in doc, f'the script does not document {needed}'


# ── The scope claim ─────────────────────────────────────────────────────────

def test_the_ui_does_not_claim_the_database_is_encrypted():
    """The database on the server is NOT encrypted by this, and the page must
    not suggest it is. Overstating what a security feature covers is how people
    make decisions they would not otherwise make."""
    with open(os.path.join(ROOT, 'templates', 'index.html'),
              encoding='utf-8', errors='replace') as fh:
        html = fh.read()
    # The export panel talks about "this file" and never about the database.
    start = html.find('id="export-encrypt"')
    assert start > 0, 'the export encryption checkbox is gone'
    panel = html[max(0, start - 1200):start + 2000].lower()
    for overclaim in ('database is encrypted', 'all your data is encrypted',
                      'end-to-end encrypted', 'fully encrypted'):
        assert overclaim not in panel, f'the export panel claims: {overclaim}'


# ── Every download path honours the passphrase ──────────────────────────────
# The bug this prevents actually shipped: the scoped export and the "download
# everything" button were wired to the passphrase box and downloadBackup() was
# not — leaving the single most complete file the app produces as the only one
# still written in the clear.

DOWNLOAD_PATHS = ['doExport', 'downloadAllData', 'downloadBackup']

TOP_LEVEL = re.compile(r'^(async function |function |const |let )')


def _js():
    return io.open(os.path.join(ROOT, 'static', 'js', 'app.js'),
                   encoding='utf-8').read()


def _function_body(name):
    lines = _js().split('\n')
    pat = re.compile(r'^(?:async )?function ' + re.escape(name) + r'\s*\(')
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    assert start is not None, f'{name} does not exist'
    end = next((j for j in range(start + 1, len(lines))
                if TOP_LEVEL.match(lines[j])), len(lines))
    return '\n'.join(lines[start:end])


@pytest.mark.parametrize('fn', DOWNLOAD_PATHS)
def test_every_download_path_asks_the_same_question(fn):
    """One helper decides, so a fourth download path cannot quietly skip it."""
    body = _function_body(fn)
    assert '_exportPassphraseOrNull()' in body, (
        f'{fn} does not consult the passphrase setting, so it writes in the '
        f'clear even when the user asked for protection')


@pytest.mark.parametrize('fn', DOWNLOAD_PATHS)
def test_a_download_stops_when_the_passphrase_cannot_be_honoured(fn):
    """Falling through to an unprotected download after the user ticked the box
    is the one outcome worse than refusing: they believe it is encrypted."""
    body = _function_body(fn)
    assert 'false' in body.split('_exportPassphraseOrNull()')[1][:120], (
        f'{fn} does not handle the "asked for, cannot honour" case')


@pytest.mark.parametrize('fn', ['doExport', 'downloadAllData', 'downloadBackup'])
def test_a_protected_download_actually_encrypts(fn):
    body = _function_body(fn)
    assert 'arogoEncrypt' in body, f'{fn} never encrypts anything'


def test_the_helper_refuses_rather_than_weakening(fn=None):
    body = _function_body('_exportPassphraseOrNull')
    assert 'arogoCryptoAvailable()' in body, 'it does not check WebCrypto exists'
    assert 'length < 8' in body, 'it does not enforce a minimum passphrase'
    # It must never silently return a usable value in those cases.
    assert body.count('return false') >= 2


# ── An encrypted backup must still be selectable ────────────────────────────

def test_the_restore_picker_accepts_encrypted_backups():
    """The file picker filtered to .json, so encrypting a backup quietly made it
    impossible to choose for a restore — protection that destroys the thing it
    protects."""
    raw = io.open(os.path.join(ROOT, 'templates', 'index.html'),
                  encoding='utf-8').read()
    m = re.search(r'<input[^>]*id="restore-file"[^>]*>', raw)
    assert m, 'the restore file input is gone'
    assert '.arogo-enc' in m.group(0), (
        'the restore picker will not show encrypted backups')


def test_the_check_picker_accepts_encrypted_backups():
    raw = io.open(os.path.join(ROOT, 'templates', 'index.html'),
                  encoding='utf-8').read()
    m = re.search(r'<input[^>]*id="check-backup-file"[^>]*>', raw)
    assert m, 'the check-a-backup input is gone'
    assert '.arogo-enc' in m.group(0)


def test_checking_a_backup_cannot_restore_it():
    """Checking must never leave the app one click away from replacing
    everything with the file being inspected."""
    body = _function_body('onCheckBackupFile')
    assert '_restoreData = null' in body, (
        'checking a file arms the restore button')
    assert 'import_all' not in body and '/api/import\'' not in body


def test_both_file_paths_share_one_reader():
    """Restore and check must agree on what "this file opens" means."""
    for fn in ('onRestoreFile', 'onCheckBackupFile'):
        assert '_readBackupFile(' in _function_body(fn), fn
