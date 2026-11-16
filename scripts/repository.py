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


def version_key(pkgver):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:(alpha|beta|rc)([1-9]\d*))?', pkgver)
    if not match:
        raise ValueError('Unsupported published version')
    major, minor, patch, stage, number = match.groups()
    return int(major), int(minor), int(patch), {'alpha': 0, 'beta': 1, 'rc': 2, None: 3}[stage], int(number or 0)


def snapshot_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def make_plan(previous=None, edition='all', validation=False):
    if edition not in ('all', *SOURCES):
        raise ValueError('Unknown edition')
    entries, blocked = [], {}
    retained = dict((previous or {}).get('packages', {}))
    for name, (repo, workflow, module) in SOURCES.items():
        if edition != 'all' and edition != name:
            continue
        head = api(repo + '/git/ref/heads/main')['object']['sha']
        if not re.fullmatch('[a-f0-9]{40}', head):
            raise ValueError('Invalid source commit')
        content = api(repo + '/contents/' + module + '?ref=' + head)
        upstream, pkgver = version(base64.b64decode(content['content']).decode())
        package = 'mirivue-' + name
        old = retained.get(package)
        # A merge without an explicitly increased application version is not
        # a publication request, even if its source commit changed.
        if old and not validation and version_key(pkgver) <= version_key(old['pkgver']):
            continue
        workflows = [workflow]
        if name == 'kde':
            workflows.append('.github/workflows/fedora-package.yml')
        runs = api(repo + '/actions/runs?per_page=100')['workflow_runs']
        selected = []
        for required in workflows:
            matching = [r for r in runs if r['head_sha'] == head and r['head_branch'] == 'main'
                        and r['event'] == 'push' and r['path'] == required]
            run = max(matching, key=lambda r: r['id']) if matching else None
            if not run or run['status'] != 'completed' or run['conclusion'] != 'success':
                blocked[name] = 'Required main workflow not successful: ' + required
                break
            selected.append(run)
        else:
            entries.append(dict(edition=name, repository=repo, sha=head, upstream=upstream,
                pkgver=pkgver, pkgrel=int(old['pkgrel']) + 1 if old and validation else 1,
                name=package, workflow_run=selected[0]['id']))
            retained.pop(package, None)
    if set(retained) | {p['name'] for p in entries} != {'mirivue-gnome', 'mirivue-kde'}:
        raise ValueError('Initial repository needs successful sources for both editions')
    return dict(schema=1, packages=entries, retained=retained, previous=previous,
                validation_only=validation, changed=bool(entries), blocked=blocked)


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
    # Arch enables debug packages by default; this repository distributes only
    # the two applications, without an additional KDE debug package.
    (destination / 'PKGBUILD').write_text(recipe + '\npkgrel=' + str(entry['pkgrel']) + "\noptions+=('!debug')\n")
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
    if not expected or not set(expected) <= {'mirivue-gnome', 'mirivue-kde'} or len(files) != len(expected):
        raise ValueError('Exactly the changed Mirivue packages are required')
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


def download_asset(name, directory):
    if not re.fullmatch(r'[A-Za-z0-9_.+~-]+', name):
        raise ValueError('Unsafe asset name')
    target = Path(directory) / name
    with urllib.request.urlopen(SERVER + '/' + name, timeout=60) as response:
        target.write_bytes(response.read(128 * 1024 * 1024 + 1))
    if target.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Asset exceeds size limit')
    return target


def retain_packages(plan, output, fingerprint, manifest):
    retained = plan.get('retained', {})
    if not retained:
        return []
    import tempfile
    trusted = os.environ.get('TRUSTED_RELEASE_FINGERPRINT', '')
    if not re.fullmatch('[A-F0-9]{40}', trusted) or plan['previous']['signing_fingerprint'] != trusted:
        raise ValueError('Published signing key differs from the independent trusted fingerprint')
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        home = root / 'gpg'; home.mkdir(mode=0o700)
        key = download_asset('mirivue-key.asc', root)
        command(['gpg', '--homedir', home, '--batch', '--import', key])
        def verify(path):
            status = command(['gpg', '--homedir', home, '--batch', '--status-fd', '1', '--verify',
                              str(path) + '.sig', path], capture_output=True, text=True).stdout
            if 'VALIDSIG ' + trusted + ' ' not in status:
                raise ValueError('Published signature has an unexpected signer')
        old_manifest = download_asset('manifest.json', root)
        download_asset('manifest.json.sig', root)
        verify(old_manifest)
        if json.loads(old_manifest.read_text()) != plan['previous']:
            raise ValueError('Published repository changed while preparing retained packages')
        paths = []
        for name, entry in retained.items():
            target = download_asset(entry['filename'], output)
            download_asset(entry['filename'] + '.sig', output)
            verify(target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Retained package checksum mismatch')
            info = package_info(target)
            if info.get('pkgname') != name or info.get('pkgver') != entry['pkgver'] + '-' + str(entry['pkgrel']):
                raise ValueError('Retained package metadata differs from signed manifest')
            if entry['source_archive'] != name + '-' + entry['source_sha'] + '-sources.tar.gz':
                raise ValueError('Retained source identity is invalid')
            archive = download_asset(entry['source_archive'], output)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != entry['source_sha256']:
                raise ValueError('Retained source checksum mismatch')
            # Disposable installation tests sign the whole catalogue with their
            # test key; production keeps each unchanged package's original sig.
            if fingerprint != trusted:
                command(['gpg', '--batch', '--yes', '--local-user', fingerprint,
                         '--output', str(target) + '.sig', '--detach-sign', target])
            paths.append(target)
            manifest['packages'][name] = dict(entry)
        return paths


def assert_publication_context(plan):
    if (plan.get('validation_only') or not plan.get('packages')
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('push', 'schedule', 'workflow_dispatch')
            or os.environ.get('PUBLISH_ENABLED') != 'true'):
        raise ValueError('This plan is not authorized for automatic publication')
    branch = api(REPOSITORY + '/branches/main')
    if not branch['protected'] or branch['commit']['sha'] != os.environ.get('GITHUB_SHA'):
        raise ValueError('Only the current protected publication branch may publish')
    previous = previous_manifest()
    if previous != plan.get('previous'):
        raise ValueError('Publication baseline changed')
    for entry in plan['packages']:
        fresh = make_plan(previous, entry['edition'])
        if fresh['packages'] != [entry]:
            raise ValueError('Source or required validation changed since planning')


def build_repository(plan, directory, output, fingerprint):
    if not re.fullmatch(r'[A-F0-9]{40}', fingerprint):
        raise ValueError('A complete signing fingerprint is required')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Repository staging directory must be empty')
    packages = collect(plan, directory)
    manifest = dict(schema=1, signing_fingerprint=fingerprint, packages={},
                    previous_manifest_sha256=snapshot_hash(plan.get('previous')))
    paths = retain_packages(plan, output, fingerprint, manifest)
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
    if manifest.get('previous_manifest_sha256') != snapshot_hash(previous):
        raise ValueError('Published manifest changed since planning; rerun validation')
    if set(manifest.get('packages', {})) != {'mirivue-gnome', 'mirivue-kde'}:
        raise ValueError('Both editions must remain in the repository')
    changed = set(manifest['packages'])
    if previous:
        if previous['signing_fingerprint'] != manifest['signing_fingerprint']:
            raise ValueError('Key rotation requires a separate explicit procedure')
        for name, item in manifest['packages'].items():
            old = previous['packages'][name]
            if item == old:
                changed.remove(name)
                continue
            if version_key(item['pkgver']) <= version_key(old['pkgver']):
                raise ValueError('Only an explicitly increased application version may publish')
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
    if not changed:
        raise ValueError('No new application version to publish')
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
    changed_files = [directory / manifest['packages'][name]['filename'] for name in changed]
    changed_files += [Path(str(path) + '.sig') for path in changed_files]
    if not changed_files:
        raise ValueError('No new application version to publish')
    command(['gh', 'release', 'upload', RELEASE, '--repo', REPOSITORY, *changed_files])
    remaining = [path for path in directory.iterdir() if path not in package_files and path not in source_files]
    # Publish the database only after all referenced packages exist remotely.
    remaining.sort(key=lambda path: ('mirivue.db' in path.name, path.name))
    for path in remaining:
        command(['gh', 'release', 'upload', RELEASE, '--repo', REPOSITORY, '--clobber', path])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'prepare', 'index', 'check', 'publish'))
    parser.add_argument('--plan', type=Path, default=Path('plan.json'))
    parser.add_argument('--edition', choices=(*SOURCES, 'all'), default='all')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--directory', type=Path, default=Path('unsigned'))
    parser.add_argument('--output', type=Path, default=Path('candidate'))
    args = parser.parse_args()
    if args.action == 'plan':
        event = os.environ.get('GITHUB_EVENT_NAME', '')
        previous = previous_manifest()
        plan = make_plan(previous, args.edition)
        # PRs and changes to this repository validate the retained-package path
        # using a disposable revision. That plan can NEVER be published.
        if not plan['changed'] and event in ('push', 'pull_request') and previous:
            plan = make_plan(previous, 'kde', validation=True)
            if not plan['packages']:
                raise ValueError('Repository changes require an installation test: ' + str(plan['blocked']))
        build = bool(plan['packages'])
        branch = api(REPOSITORY + '/branches/main')
        should_publish = (build and not plan['validation_only'] and event in ('push', 'schedule', 'workflow_dispatch')
                   and os.environ.get('GITHUB_REF') == 'refs/heads/main'
                   and os.environ.get('PUBLISH_ENABLED') == 'true' and branch['protected'])
        args.plan.write_text(json.dumps(plan, indent=2) + '\n')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('build=' + str(build).lower() + '\n')
                stream.write('publish=' + str(should_publish).lower() + '\n')
                stream.write('matrix=' + json.dumps({'include': plan['packages']}, separators=(',', ':')) + '\n')
        print('Validated sources; build required: ' + str(build))
        for edition, reason in plan['blocked'].items():
            print(f'{edition}: retained published package ({reason})')
    elif args.action == 'prepare':
        plan = json.loads(args.plan.read_text())
        entry = next(item for item in plan['packages'] if item['edition'] == args.edition)
        prepare_build(entry, args.source, args.directory)
    elif args.action == 'check':
        assert_publication_context(json.loads(args.plan.read_text()))
    elif args.action == 'index':
        build_repository(json.loads(args.plan.read_text()), args.directory, args.output, os.environ['SIGNING_FINGERPRINT'])
    else:
        plan = json.loads(args.plan.read_text())
        assert_publication_context(plan)
        publish(args.directory)


if __name__ == '__main__':
    main()
