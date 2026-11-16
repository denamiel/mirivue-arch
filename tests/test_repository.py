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
    def test_publish_command_checks_context_then_calls_publisher(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / 'plan.json'
            plan.write_text(json.dumps({'packages': [{'edition': 'kde'}]}))
            events = []
            with patch.object(sys, 'argv', ['repository.py', 'publish', '--plan', str(plan),
                                           '--directory', str(root / 'candidate')]), \
                    patch.object(repo, 'assert_publication_context', side_effect=lambda value: events.append('check')), \
                    patch.object(repo, 'publish', side_effect=lambda directory: events.append('publish')) as publisher:
                repo.main()
            self.assertEqual(events, ['check', 'publish'])
            publisher.assert_called_once_with(root / 'candidate')

    def fake_api(self, path, optional=False):
        if '/git/ref/' in path:
            return {'object': {'sha': 'a' * 40}}
        if '/actions/runs' in path:
            edition = 'gnome' if 'Mirivue-gnome' in path else 'kde'
            return {'workflow_runs': [{'head_sha': 'a' * 40, 'head_branch': 'main', 'event': 'push',
                'path': workflow, 'status': 'completed', 'conclusion': 'success', 'id': 12+i} for i, workflow in enumerate([repo.SOURCES[edition][1]] + (['.github/workflows/fedora-package.yml'] if edition=='kde' else []))]}
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

    def test_same_version_never_rebuilds_even_when_main_commit_changes(self):
        old = {'packages': {name: {'pkgver':'1.0.0beta2','pkgrel':3,'source_sha':'b'*40}
                           for name in ('mirivue-gnome','mirivue-kde')}}
        with patch.object(repo,'api',side_effect=self.fake_api):plan=repo.make_plan(old)
        self.assertFalse(plan['changed'])
        self.assertEqual(plan['packages'],[])
        self.assertEqual(plan['retained'],old['packages'])

    def test_kde_only_release_does_not_read_or_rebuild_gnome(self):
        old={'packages': {'mirivue-gnome':{'pkgver':'1.0.0beta2','pkgrel':19,'source_sha':'b'*40},
                          'mirivue-kde':{'pkgver':'1.0.0beta1','pkgrel':1,'source_sha':'b'*40}}}
        def api(path,optional=False):
            self.assertNotIn('Mirivue-gnome',path)
            return self.fake_api(path,optional)
        with patch.object(repo,'api',side_effect=api):plan=repo.make_plan(old,'kde')
        self.assertEqual([p['name'] for p in plan['packages']],['mirivue-kde'])
        self.assertEqual(plan['retained'],{'mirivue-gnome':old['packages']['mirivue-gnome']})
        self.assertEqual(plan['packages'][0]['pkgrel'],1)

    def test_failed_gnome_new_version_does_not_block_successful_kde(self):
        old={'packages': {name:{'pkgver':'1.0.0beta1','pkgrel':1,'source_sha':'b'*40}
                          for name in ('mirivue-gnome','mirivue-kde')}}
        def api(path,optional=False):
            result=self.fake_api(path,optional)
            if 'Mirivue-gnome' in path and 'workflow_runs' in result:
                result['workflow_runs'][0]['conclusion']='failure'
            return result
        with patch.object(repo,'api',side_effect=api):plan=repo.make_plan(old)
        self.assertEqual([p['name'] for p in plan['packages']],['mirivue-kde'])
        self.assertEqual(plan['retained']['mirivue-gnome'],old['packages']['mirivue-gnome'])
        self.assertIn('gnome',plan['blocked'])

    def test_ci_simulation_never_gets_publication_authorization(self):
        import os
        plan={'validation_only':True,'packages':[{}]}
        with patch.dict(os.environ,{'GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'push','PUBLISH_ENABLED':'true'}):
            with patch.object(repo,'api') as api:
                with self.assertRaises(ValueError):repo.assert_publication_context(plan)
                api.assert_not_called()

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
            self.assertIn("options+=('!debug')", (second / 'PKGBUILD').read_text())

    def test_stale_baseline_and_same_version_cannot_upload(self):
        old={'schema':1,'signing_fingerprint':'A'*40,'packages':{
            name:{'pkgver':'1.0.0beta2','pkgrel':1,'filename':name+'.pkg.tar.zst'}
            for name in ('mirivue-gnome','mirivue-kde')}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            candidate=dict(old,previous_manifest_sha256=repo.snapshot_hash(old))
            (root/'manifest.json').write_text(json.dumps(candidate))
            with patch.object(repo,'previous_manifest',return_value=dict(old,signing_fingerprint='B'*40)),patch.object(repo,'command') as calls:
                with self.assertRaises(ValueError):repo.publish(root)
                calls.assert_not_called()
            with patch.object(repo,'previous_manifest',return_value=old),patch.object(repo,'command') as calls:
                with self.assertRaises(ValueError):repo.publish(root)
                calls.assert_not_called()

    def test_collect_accepts_one_changed_edition_and_rejects_extra_files(self):
        plan={'packages':[{'name':'mirivue-kde','pkgver':'1.0.3','pkgrel':1}]}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'mirivue-kde.pkg.tar.zst';p.write_bytes(b'package')
            with patch.object(repo,'package_info',return_value={'pkgname':'mirivue-kde','pkgver':'1.0.3-1','arch':'x86_64'}):
                self.assertEqual(set(repo.collect(plan,folder)),{'mirivue-kde'})
                (Path(folder)/'extra.pkg.tar.zst').write_bytes(b'extra')
                with self.assertRaises(ValueError):repo.collect(plan,folder)

    def test_retention_refuses_untrusted_owner_key_before_downloading(self):
        import os
        plan={'retained':{'mirivue-gnome':{}},'previous':{'signing_fingerprint':'B'*40}}
        with patch.dict(os.environ,{'TRUSTED_RELEASE_FINGERPRINT':'A'*40}),patch.object(repo,'download_asset') as download:
            with self.assertRaises(ValueError):repo.retain_packages(plan,Path('/unused'),'A'*40,{})
            download.assert_not_called()
