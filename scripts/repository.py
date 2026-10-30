#!/usr/bin/env python3
"""Pacman repository planning, package verification and publication.
SPDX-License-Identifier: GPL-3.0-or-later
"""
import argparse
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

REPOSITORY = 'denamiel/mirivue-arch'
RELEASE = 'repository'
SERVER = f'https://github.com/{REPOSITORY}/releases/download/{RELEASE}'
SOURCES = {
    'gnome': ('denamiel/Mirivue-gnome', '.github/workflows/checks.yml', 'mirivue_gtk4/__init__.py'),
    'kde': ('denamiel/Mirivue-kde', '.github/workflows/arch-package.yml', 'mirivue/__init__.py'),
}
VERSION = re.compile(r'(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.([1-9]\d*))?\Z')


def command(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def api(path, optional=False):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Mirivue-Arch'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    request = urllib.request.Request('https://api.github.com/repos/' + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if optional and error.code == 404:
            return None
        raise


def version(text):
    tree = ast.parse(text)
    value = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets))
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError('Unsupported upstream version')
    base, stage, number = match.groups()
    return value, base + (stage + number if stage else '')


def previous_manifest():
    release = api(REPOSITORY + '/releases/tags/' + RELEASE, True)
    if release is None:
        return None
    asset = next((item for item in release['assets'] if item['name'] == 'manifest.json'), None)
    if not asset:
        raise ValueError('Published repository has no manifest; refusing to guess its state')
    with urllib.request.urlopen(asset['browser_download_url'], timeout=40) as response:
        data = json.load(response)
    if data.get('schema') != 1 or set(data.get('packages', {})) != {'mirivue-gnome', 'mirivue-kde'}:
        raise ValueError('Unsupported repository manifest')
    return data


def make_plan(previous=None):
    entries = []
    changed = previous is None
    for edition, (repo, workflow, module) in SOURCES.items():
        head = api(repo + '/git/ref/heads/main')['object']['sha']
        if not re.fullmatch('[a-f0-9]{40}', head):
            raise ValueError('Invalid source commit')
        runs = api(repo + '/actions/runs?per_page=100')['workflow_runs']
        run = next((item for item in runs if item['head_sha'] == head and item['head_branch'] == 'main'
                    and item['event'] == 'push' and item['path'] == workflow), None)
        if not run or run['status'] != 'completed' or run['conclusion'] != 'success':
            raise ValueError(f'{repo}: the current main commit has not passed its required workflow')
        content = api(repo + '/contents/' + module + '?ref=' + head)
        upstream, pkgver = version(base64.b64decode(content['content']).decode())
        name = 'mirivue-' + edition
        old = (previous or {}).get('packages', {}).get(name)
        revision = int(old['pkgrel']) + 1 if old and old['pkgver'] == pkgver else 1
        if old and (old['source_sha'] != head or old['pkgver'] != pkgver):
            changed = True
        entries.append(dict(edition=edition, repository=repo, sha=head, upstream=upstream,
                            pkgver=pkgver, pkgrel=revision, name=name, workflow_run=run['id']))
    return dict(schema=1, packages=entries, changed=changed)


def prepare_build(entry, source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    repo, _workflow, module = SOURCES[entry['edition']]
    if entry['repository'] != repo or version((source / module).read_text()) != (entry['upstream'], entry['pkgver']):
        raise ValueError('Source version does not match the validated build plan')
    if entry['edition'] == 'gnome':
        command(['python', source / 'packaging/make_source.py', '--output', destination, '--no-aur'])
        archive = destination / ('mirivue-gnome-' + entry['upstream'] + '.tar.gz')
        recipe = (source / 'packaging/arch/PKGBUILD.in').read_text()
        recipe = recipe.replace('@VERSION@', entry['upstream']).replace('@ARCH_VERSION@', entry['pkgver'])
        recipe = recipe.replace('@SHA256@', hashlib.sha256(archive.read_bytes()).hexdigest())
    else:
        archive = destination / 'mirivue-source.tar.gz'
        command(['tar', '-C', source, '--exclude=./.git', '--exclude=./.github', '--exclude=./build',
                 '--exclude=./src', '--exclude=./pkg', '--exclude=*.pkg.tar.*', '--exclude=*.zip',
                 '--exclude=__pycache__', '--exclude=*.pyc', '--sort=name', '--mtime=@0', '--owner=0',
                 '--group=0', '--numeric-owner', '--transform=s,^\\.,mirivue-source,',
                 '-czf', archive, '.'])
        recipe = (source / 'packaging/PKGBUILD.template').read_text()
        recipe = recipe.replace('@PKGVER@', entry['pkgver']).replace(
            '@SOURCE_SHA256@', hashlib.sha256(archive.read_bytes()).hexdigest())
    if not re.search(r'^pkgname=' + re.escape(entry['name']) + '$', recipe, re.M):
        raise ValueError('Unexpected package name in recipe')
    # A repository rebuild must have a new pkgrel even when the source version
    # stays the same. The upstream applications and settings are not changed.
    (destination / 'PKGBUILD').write_text(recipe + '\npkgrel=' + str(entry['pkgrel']) + '\n')
    source_artifact = destination / 'source-artifact'
    source_artifact.mkdir(exist_ok=True)
    shutil.copyfile(archive, source_artifact / (entry['name'] + '-' + entry['sha'] + '-sources.tar.gz'))


def package_info(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or not re.fullmatch(r'[A-Za-z0-9_.+~\-]+\.pkg\.tar\.zst', path.name):
        raise ValueError('Invalid package filename')
    result = command(['bsdtar', '-xOf', path, '.PKGINFO'], capture_output=True, text=True).stdout
    fields = {}
    for line in result.splitlines():
        if ' = ' in line and not line.startswith('#'):
            key, value = line.split(' = ', 1)
            fields.setdefault(key, []).append(value)
    return {key: fields[key][0] for key in ('pkgname', 'pkgver', 'arch') if len(fields.get(key, [])) == 1}


def collect(plan, directory):
    files = list(Path(directory).rglob('*.pkg.tar.zst'))
    expected = {entry['name']: entry for entry in plan['packages']}
    if set(expected) != {'mirivue-gnome', 'mirivue-kde'} or len(files) != 2:
        raise ValueError('Exactly the two Mirivue packages are required')
    result = {}
    for path in files:
        info = package_info(path)
        name = info.get('pkgname')
        if name not in expected or name in result:
            raise ValueError('Unexpected or duplicate package')
        entry = expected[name]
        if info.get('pkgver') != entry['pkgver'] + '-' + str(entry['pkgrel']):
            raise ValueError('Package version differs from build plan')
        if info.get('arch') not in ('any', 'x86_64'):
            raise ValueError('Unsupported package architecture')
        result[name] = (path, entry)
    return result


def build_repository(plan, directory, output, fingerprint):
    if not re.fullmatch(r'[A-F0-9]{40}', fingerprint):
        raise ValueError('A complete signing fingerprint is required')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Repository staging directory must be empty')
    packages = collect(plan, directory)
    manifest = dict(schema=1, signing_fingerprint=fingerprint, packages={})
    paths = []
    for name, (source, entry) in packages.items():
        target = output / source.name
        shutil.copyfile(source, target)
        command(['gpg', '--batch', '--yes', '--local-user', fingerprint, '--output', str(target) + '.sig', '--detach-sign', target])
        command(['gpg', '--verify', str(target) + '.sig', target])
        paths.append(target)
        archive_name = name + '-' + entry['sha'] + '-sources.tar.gz'
        archives = list(Path(directory).rglob(archive_name))
        if len(archives) != 1 or archives[0].is_symlink():
            raise ValueError('The corresponding source archive is required')
        archive_target = output / archive_name
        shutil.copyfile(archives[0], archive_target)
        manifest['packages'][name] = dict(source_archive=archive_name,
            source_sha256=hashlib.sha256(archive_target.read_bytes()).hexdigest(), pkgver=entry['pkgver'], pkgrel=entry['pkgrel'],
            filename=target.name, sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            source_repository=entry['repository'], source_sha=entry['sha'], workflow_run=entry['workflow_run'])
    command(['repo-add', '--sign', '--key', fingerprint, output / 'mirivue.db.tar.gz', *paths])
    # GitHub release assets must be regular files, including the .db aliases
    # requested by pacman. All aliases contain exactly the signed bytes.
    for stem in ('mirivue.db', 'mirivue.files'):
        original = output / (stem + '.tar.gz')
        signature = Path(str(original) + '.sig')
        if not signature.exists():
            command(['gpg', '--batch', '--local-user', fingerprint, '--output', signature, '--detach-sign', original])
        command(['gpg', '--verify', signature, original])
        for suffix, source in (('', original), ('.sig', signature)):
            alias = output / (stem + suffix)
            if alias.is_symlink():
                alias.unlink()
            shutil.copyfile(source, alias)
    with (output / 'mirivue-key.asc').open('wb') as stream:
        command(['gpg', '--armor', '--export', fingerprint], stdout=stream)
    (output / 'fingerprint.txt').write_text(fingerprint + '\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    command(['gpg', '--batch', '--local-user', fingerprint, '--output', output / 'manifest.json.sig',
             '--detach-sign', output / 'manifest.json'])
    (output / 'mirivue.conf').write_text('[mirivue]\nSigLevel = Required DatabaseRequired\nServer = ' + SERVER + '\n')
    return manifest


def publish(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    previous = previous_manifest()
    if previous:
        if previous['signing_fingerprint'] != manifest['signing_fingerprint']:
            raise ValueError('Key rotation requires a separate explicit procedure')
        for name, item in manifest['packages'].items():
            old = previous['packages'][name]
            if (old.get('source_archive') == item.get('source_archive')
                    and old.get('source_sha256') != item.get('source_sha256')):
                raise ValueError('An existing source archive must retain its exact checksum')
            new_version = item['pkgver'] + '-' + str(item['pkgrel'])
            old_version = old['pkgver'] + '-' + str(old['pkgrel'])
            compared = command(['vercmp', new_version, old_version], capture_output=True, text=True).stdout.strip()
            if int(compared) <= 0:
                raise ValueError('Refusing a repository downgrade or same-version replacement')
    else:
        command(['gh', 'release', 'create', RELEASE, '--repo', REPOSITORY, '--target', os.environ['GITHUB_SHA'],
                 '--title', 'Mirivue — dépôt Pacman', '--notes', 'Signed Arch Linux / CachyOS packages.', '--prerelease'])
    # Upload immutable versioned packages first. Keep older package assets.
    package_files = [directory / item['filename'] for item in manifest['packages'].values()]
    package_files += [Path(str(path) + '.sig') for path in package_files]
    source_files = [directory / item['source_archive'] for item in manifest['packages'].values()]
    # An unchanged upstream source can be shared by several pkgrel rebuilds.
    known_assets = api(REPOSITORY + '/releases/tags/' + RELEASE)['assets']
    known_names = {item['name'] for item in known_assets}
    for path in source_files:
        if path.name not in known_names:
            command(['gh', 'release', 'upload', RELEASE, '--repo', REPOSITORY, path])
    command(['gh', 'release', 'upload', RELEASE, '--repo', REPOSITORY, *package_files])
    remaining = [path for path in directory.iterdir() if path not in package_files and path not in source_files]
    # Publish the database only after all referenced packages exist remotely.
    remaining.sort(key=lambda path: ('mirivue.db' in path.name, path.name))
    for path in remaining:
        command(['gh', 'release', 'upload', RELEASE, '--repo', REPOSITORY, '--clobber', path])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'prepare', 'index', 'publish'))
    parser.add_argument('--plan', type=Path, default=Path('plan.json'))
    parser.add_argument('--edition', choices=SOURCES)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--directory', type=Path, default=Path('unsigned'))
    parser.add_argument('--output', type=Path, default=Path('candidate'))
    args = parser.parse_args()
    if args.action == 'plan':
        event = os.environ.get('GITHUB_EVENT_NAME', '')
        enabled = os.environ.get('PUBLISH_ENABLED') == 'true'
        if event == 'schedule' and not enabled:
            plan = dict(schema=1, packages=[], changed=False)
        else:
            plan = make_plan(previous_manifest())
        build = bool(plan['packages']) and (plan['changed'] or event not in ('schedule', 'workflow_dispatch')
                                            or os.environ.get('FORCE_REBUILD') == 'true')
        args.plan.write_text(json.dumps(plan, indent=2) + '\n')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('build=' + str(build).lower() + '\n')
                stream.write('matrix=' + json.dumps({'include': plan['packages']}, separators=(',', ':')) + '\n')
        print('Validated sources; build required: ' + str(build))
    elif args.action == 'prepare':
        plan = json.loads(args.plan.read_text())
        entry = next(item for item in plan['packages'] if item['edition'] == args.edition)
        prepare_build(entry, args.source, args.directory)
    elif args.action == 'index':
        build_repository(json.loads(args.plan.read_text()), args.directory, args.output, os.environ['SIGNING_FINGERPRINT'])
    else:
        publish(args.directory)


if __name__ == '__main__':
    main()
