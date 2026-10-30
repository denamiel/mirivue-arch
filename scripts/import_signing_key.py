#!/usr/bin/env python3
"""Import a GitHub signing secret into an isolated, temporary GnuPG home.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import os
from pathlib import Path
import re
import subprocess


def main():
    os.umask(0o077)
    home = Path(os.environ['GNUPGHOME']).resolve()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(home.iterdir()):
        raise ValueError('Signing home must be empty')
    fingerprint = os.environ['SIGNING_FINGERPRINT']
    secret = os.environ.get('SIGNING_PRIVATE_KEY', '')
    password = os.environ.get('SIGNING_PASSPHRASE', '')
    if not re.fullmatch('[A-F0-9]{40}', fingerprint) or not secret.startswith('-----BEGIN PGP PRIVATE KEY BLOCK-----'):
        raise ValueError('Configure the signing fingerprint and private-key secret before publishing')
    if not password or '\n' in password or '\r' in password:
        raise ValueError('A non-empty, single-line signing passphrase is required')
    password_file = home / 'passphrase'
    password_file.write_text(password + '\n')
    (home / 'gpg.conf').write_text('batch\npinentry-mode loopback\npassphrase-file ' + str(password_file) + '\n')
    private = home / 'import.asc'
    try:
        private.write_text(secret)
        subprocess.run(['gpg', '--batch', '--quiet', '--import', str(private)], check=True)
    finally:
        private.unlink(missing_ok=True)
    result = subprocess.check_output(['gpg', '--batch', '--with-colons', '--fingerprint', '--list-secret-keys'], text=True)
    primaries, wanted = [], False
    for line in result.splitlines():
        fields = line.split(':')
        if fields[0] == 'sec':
            wanted = True
        elif fields[0] == 'fpr' and wanted:
            primaries.append(fields[9])
            wanted = False
    if primaries != [fingerprint]:
        raise ValueError('The imported key does not match the configured fingerprint')


if __name__ == '__main__':
    main()
