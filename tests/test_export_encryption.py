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
import json
import os
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
