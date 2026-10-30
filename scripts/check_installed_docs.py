#!/usr/bin/env python3
"""Compare installed guides to the corresponding published sources."""
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import sys
import tarfile

directory = Path(sys.argv[1])
manifest = json.loads((directory / 'manifest.json').read_text())
for name, package in manifest['packages'].items():
    documents = ['README.md', 'CHANGELOG.md']
    documents += (['LISEZ-MOI-KDE.txt', 'packaging/README.md', 'packaging/fedora/PUBLICATION.md']
                  if name == 'mirivue-kde' else ['BETA-1.0.0.md', 'packaging/PUBLICATION.md'])
    with tarfile.open(directory / package['source_archive']) as archive:
        for document in documents:
            members = [m for m in archive.getmembers()
                       if m.isfile() and m.name.split('/', 1)[-1] == document]
            if len(members) != 1:
                raise ValueError(f'Source documentaire absente ou ambiguë : {name}/{document}')
            installed = Path('/usr/share/doc') / name / document
            if installed.is_symlink() or installed.read_bytes() != archive.extractfile(members[0]).read():
                raise ValueError(f'Document installé différent des sources : {installed}')
    print(f'{name} : guides installés identiques aux sources publiées')
