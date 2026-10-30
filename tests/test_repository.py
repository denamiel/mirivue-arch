"""Repository decisions must not publish unvalidated or mismatched packages."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('repository', Path(__file__).resolve().parents[1] / 'scripts/repository.py')
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


class RepositoryTests(unittest.TestCase):
    def fake_api(self, path, optional=False):
        if '/git/ref/' in path:
            return {'object': {'sha': 'a' * 40}}
        if '/actions/runs' in path:
            edition = 'gnome' if 'Mirivue-gnome' in path else 'kde'
            return {'workflow_runs': [{'head_sha': 'a' * 40, 'head_branch': 'main', 'event': 'push',
                'path': repo.SOURCES[edition][1], 'status': 'completed', 'conclusion': 'success', 'id': 12}]}
        if '/contents/' in path:
            return {'content': base64.b64encode(b'__version__ = "1.0.0-beta.2"').decode()}
        raise AssertionError(path)

    def test_only_current_main_commit_with_successful_required_workflow_is_selected(self):
        with patch.object(repo, 'api', side_effect=self.fake_api):
            plan = repo.make_plan()
        self.assertEqual({entry['name'] for entry in plan['packages']}, {'mirivue-gnome', 'mirivue-kde'})
        self.assertTrue(plan['changed'])
        self.assertTrue(all(entry['sha'] == 'a' * 40 for entry in plan['packages']))

    def test_failed_pending_old_commit_or_pull_request_never_pass_the_gate(self):
        for change in ({'conclusion': 'failure'}, {'status': 'in_progress'}, {'head_sha': 'b' * 40}, {'event': 'pull_request'}):
            def api(path, optional=False):
                result = self.fake_api(path, optional)
                if 'workflow_runs' in result:
                    result['workflow_runs'][0].update(change)
                return result
            with self.subTest(change=change), patch.object(repo, 'api', side_effect=api):
                with self.assertRaises(ValueError):
                    repo.make_plan()

    def test_unchanged_source_skips_publication_and_rebuild_gets_a_new_revision(self):
        old = {'packages': {name: {'pkgver': '1.0.0beta2', 'pkgrel': 3, 'source_sha': 'a' * 40}
                           for name in ('mirivue-gnome', 'mirivue-kde')}}
        with patch.object(repo, 'api', side_effect=self.fake_api):
            plan = repo.make_plan(old)
        self.assertFalse(plan['changed'])
        self.assertEqual([entry['pkgrel'] for entry in plan['packages']], [4, 4])
        old['packages']['mirivue-kde']['source_sha'] = 'b' * 40
        with patch.object(repo, 'api', side_effect=self.fake_api):
            self.assertTrue(repo.make_plan(old)['changed'])

    def test_invalid_version_and_code_instead_of_a_literal_are_rejected(self):
        for value in ('1.0.0;touch x', '../bad', '1.0.0-beta.0'):
            with self.assertRaises(ValueError):
                repo.version('__version__ = ' + repr(value))
        with self.assertRaises(ValueError):
            repo.version('__version__ = __import__("os").getcwd()')
        self.assertEqual(repo.version('__version__ = "1.0.0-beta.2"'), ('1.0.0-beta.2', '1.0.0beta2'))

    def test_missing_duplicate_or_wrong_version_artifact_is_rejected(self):
        with patch.object(repo, 'api', side_effect=self.fake_api):
            plan = repo.make_plan()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / 'one.pkg.tar.zst'; first.write_bytes(b'one')
            with self.assertRaises(ValueError):
                repo.collect(plan, root)
            second = root / 'two.pkg.tar.zst'; second.write_bytes(b'two')
            with patch.object(repo, 'package_info', return_value={'pkgname': 'mirivue-gnome', 'pkgver': '9.0-1', 'arch': 'any'}):
                with self.assertRaises(ValueError):
                    repo.collect(plan, root)
            with patch.object(repo, 'package_info', return_value={'pkgname': 'mirivue-gnome', 'pkgver': '1.0.0beta2-1', 'arch': 'any'}):
                with self.assertRaises(ValueError):
                    repo.collect(plan, root)
            second.unlink(); second.symlink_to(first)
            with self.assertRaises(ValueError):
                repo.package_info(second)

    def test_corresponding_source_archives_are_reproducible_for_rebuilds(self):
        import hashlib
        import os
        import tarfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'upstream'
            (source / 'mirivue').mkdir(parents=True)
            (source / 'packaging').mkdir()
            (source / 'mirivue/__init__.py').write_text('__version__ = "1.0.0-beta.2"')
            (source / 'packaging/PKGBUILD.template').write_text('pkgname=mirivue-kde\npkgver=@PKGVER@\npkgrel=1\n')
            entry = dict(edition='kde', repository=repo.SOURCES['kde'][0], upstream='1.0.0-beta.2',
                         pkgver='1.0.0beta2', pkgrel=3, name='mirivue-kde', sha='a' * 40)
            first, second = root / 'first', root / 'second'
            repo.prepare_build(entry, source, first)
            os.utime(source / 'mirivue/__init__.py', (500, 500))
            repo.prepare_build(entry, source, second)
            first_archive = next((first / 'source-artifact').iterdir())
            second_archive = next((second / 'source-artifact').iterdir())
            self.assertEqual(hashlib.sha256(first_archive.read_bytes()).digest(),
                             hashlib.sha256(second_archive.read_bytes()).digest())
            with tarfile.open(first_archive) as archive:
                self.assertIn('mirivue-source/mirivue/__init__.py', archive.getnames())
            self.assertIn('pkgrel=3', (second / 'PKGBUILD').read_text())

    def test_downgrade_and_unannounced_signing_key_change_prevent_uploads(self):
        current = {'schema': 1, 'signing_fingerprint': 'A' * 40,
                   'packages': {name: {'pkgver': '1.0.0beta2', 'pkgrel': 1, 'filename': name + '.pkg.tar.zst'}
                                for name in ('mirivue-gnome', 'mirivue-kde')}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'manifest.json').write_text(json.dumps(current))
            changed = dict(current, signing_fingerprint='B' * 40)
            with patch.object(repo, 'previous_manifest', return_value=changed), patch.object(repo, 'command') as calls:
                with self.assertRaises(ValueError):
                    repo.publish(root)
                calls.assert_not_called()
            with patch.object(repo, 'previous_manifest', return_value=current), patch.object(repo, 'command') as calls:
                calls.return_value.stdout = '0'
                with self.assertRaises(ValueError):
                    repo.publish(root)
                self.assertEqual(calls.call_count, 1)
