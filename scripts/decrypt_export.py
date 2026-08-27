#!/usr/bin/env python3
"""Open an Arogo encrypted export without Arogo.

    python scripts/decrypt_export.py arogo-export-2026-08-26.json.arogo-enc

This script exists because the alternative is unacceptable. An export is how
someone takes their data OUT of this app — to another tool, to a doctor, to a
lawyer, to whatever comes after Arogo stops being maintained. Encrypting it with
a scheme only Arogo can undo would quietly convert "your data is yours" into
"your data is yours as long as you keep running our software", which is the
opposite of the point.

So the format is deliberately boring, standard, and self-describing:

    AROGO-ENC1
    {"kdf":"PBKDF2-SHA256","iterations":600000,"salt":"…","cipher":"AES-256-GCM","iv":"…"}
    <base64 ciphertext with the GCM tag appended>

Line 1 identifies it. Line 2 carries every parameter needed to derive the key —
nothing is implied, nothing is hardcoded on the reading side. Line 3 onwards is
the ciphertext. Any language with PBKDF2-HMAC-SHA256 and AES-256-GCM can read
it; this script is a convenience, not a dependency.

The passphrase is never stored anywhere, by design. If it is lost the file
cannot be recovered — not by this script, not by Arogo, not by anyone.

Needs `cryptography` for AES-GCM (`pip install cryptography`). PBKDF2 comes from
the standard library.
"""
import argparse
import base64
import getpass
import hashlib
import json
import sys

MAGIC = 'AROGO-ENC1'
SUPPORTED_KDF = 'PBKDF2-SHA256'
SUPPORTED_CIPHER = 'AES-256-GCM'


def parse(blob: str):
    """(header, ciphertext_bytes) or a clear error about why not."""
    lines = blob.split('\n')
    if not lines or lines[0].strip() != MAGIC:
        raise ValueError(
            f'Not an Arogo encrypted export (expected a first line of {MAGIC!r}). '
            'A plain .json export needs no decrypting — open it directly.')
    try:
        header = json.loads(lines[1])
    except (IndexError, ValueError):
        raise ValueError('The header line is missing or not valid JSON. The '
                         'file looks truncated.')
    if header.get('kdf') != SUPPORTED_KDF or header.get('cipher') != SUPPORTED_CIPHER:
        # Refused rather than guessed: a wrong guess surfaces as "wrong
        # passphrase", which sends someone hunting for a typo that isn't there.
        raise ValueError(
            f'This file uses {header.get("kdf")!r} + {header.get("cipher")!r}, '
            f'and this script only implements {SUPPORTED_KDF} + {SUPPORTED_CIPHER}. '
            'Everything needed is in the header line above — any tool that '
            'implements those will open it.')
    ct = base64.b64decode(''.join(lines[2:]).strip())
    return header, ct


def decrypt(blob: str, passphrase: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise SystemExit(
            'This script needs the `cryptography` package for AES-GCM:\n'
            '    pip install cryptography\n'
            'The format itself is standard — any AES-256-GCM tool will do.')
    header, ct = parse(blob)
    key = hashlib.pbkdf2_hmac(
        'sha256', passphrase.encode('utf-8'),
        base64.b64decode(header['salt']), int(header['iterations']), dklen=32)
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(header['iv']), ct, None)
    except Exception:
        # AES-GCM authenticates, so a failure here means the passphrase is wrong
        # OR the file was altered. There is no way to tell which, and claiming
        # to know would be a guess presented as a fact.
        raise ValueError('That passphrase did not open the file. Either it is '
                         'wrong, or the file has been altered since it was '
                         'written.')
    return plain.decode('utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('file', help='the .arogo-enc file to open')
    ap.add_argument('-o', '--out', help='write here instead of standard output')
    ap.add_argument('--passphrase', help='prompted for if omitted, which is '
                                         'safer — this lands in your shell history')
    args = ap.parse_args()

    with open(args.file, encoding='utf-8') as fh:
        blob = fh.read()

    passphrase = args.passphrase or getpass.getpass('Passphrase: ')
    try:
        plain = decrypt(blob, passphrase)
    except ValueError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(plain)
        print(f'Wrote {len(plain)} characters to {args.out}', file=sys.stderr)
    else:
        sys.stdout.write(plain)
    return 0


if __name__ == '__main__':
    sys.exit(main())
