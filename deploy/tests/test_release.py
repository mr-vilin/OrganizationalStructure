"""发布的环境隔离、制品完整性、迁移阻断及失败恢复测试。"""
import json
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from deploy import release
from release_host import Host, require_idle, require_schema, write_json


class ReleaseTests(unittest.TestCase):
    def test_archive_configuration_digest_uses_the_requested_image(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'image.tar'
            config = b'{"architecture":"amd64","os":"linux"}'
            with tarfile.open(archive, 'w') as bundle:
                for name, data in [('manifest.json', json.dumps([
                    {'RepoTags': ['other:tag'], 'Config': 'other.json'},
                    {'RepoTags': ['app:release'], 'Config': 'config.json'},
                ]).encode()), ('config.json', config)]:
                    item = tarfile.TarInfo(name)
                    item.size = len(data)
                    bundle.addfile(item, io.BytesIO(data))
            self.assertEqual(release.image_config_id(archive, 'app:release'),
                             'sha256:' + hashlib.sha256(config).hexdigest())
            with self.assertRaisesRegex(RuntimeError, 'IMAGE_ARCHIVE_TAG_MISMATCH'):
                release.image_config_id(archive, 'missing:tag')

    def test_switch_uses_the_target_engine_image_id_and_rejects_other_images(self):
        for actual in ('sha256:index', 'sha256:config', 'sha256:other'):
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as directory:
                host = Host({'root': directory, 'compose': 'compose.yaml', 'project': 'test',
                             'services': ['app', 'mcp'], 'transport': 'ssh'})
                before = {'schema': 'head', 'active_jobs': 0, 'flow_phase': 'pending',
                          'state': {'initialization_status': 'pending'}, 'counts': {}, 'build': {}}
                manifest = {'schema': 'head', 'image': 'new', 'image_id': 'sha256:index',
                            'image_config_id': 'sha256:config', 'release_id': 'release-test', 'build': {}}
                def command(args, **kwargs):
                    if args[:3] == ['docker', 'image', 'inspect']:
                        return actual
                    return json.dumps(before) if args[-1] == '-' else ''
                with patch('release_host.run', side_effect=command), patch.object(host, 'probe', return_value=before), \
                     patch.object(host, 'images', return_value={'app': 'sha256:old'}), \
                     patch.object(host, 'up') as up, patch.object(host, 'verify', return_value={'build': {}, 'assets': []}) as verify:
                    if actual == 'sha256:other':
                        with self.assertRaisesRegex(RuntimeError, 'IMAGE_ID_MISMATCH'):
                            host.apply(manifest)
                        up.assert_not_called()
                        self.assertFalse(host.archive_root.exists())
                    else:
                        self.assertEqual(host.apply(manifest)['status'], 'deployed')
                        verify.assert_called_once_with(actual)
                        self.assertEqual(json.loads(host.override.read_text())['services']['app']['image'], actual)

    def test_stopped_app_probe_uses_one_off_without_starting_workers(self):
        host = Host({'root': '.', 'compose': 'compose.yaml', 'project': 'test'})
        with patch('release_host.run', side_effect=['', '{"schema": "0010"}']) as command:
            self.assertEqual(host.probe('snapshot()'), {'schema': '0010'})
        args = command.call_args_list[1].args[0]
        self.assertEqual(args[-7:], ['run', '--rm', '--no-deps', '-T', 'app', 'python', '-'])

    def test_remote_deploy_requires_explicit_authorization_but_read_is_allowed(self):
        for action in ('deploy', 'rollback'):
            with self.assertRaisesRegex(RuntimeError, 'REMOTE_AUTHORIZATION_REQUIRED'):
                release.environment('test', action, '')
        self.assertEqual(release.environment('test', 'inspect', '')['ssh_host'], 'tencent_test_col')
        self.assertEqual(release.environment('local', 'deploy', '')['root'], str(release.ROOT))

    def test_production_is_not_test_alias_even_with_authorization(self):
        with self.assertRaisesRegex(RuntimeError, 'ENVIRONMENT_NOT_CONFIGURED'):
            release.environment('production', 'deploy', '用户明确要求部署正式环境')

    def test_schema_and_active_jobs_block(self):
        with self.assertRaisesRegex(RuntimeError, 'MIGRATION_REQUIRED'):
            require_schema({'schema': '0009_operation_receipt'}, '0010_initialization_wizard')
        for state in ({'active_jobs': 1, 'flow_phase': 'pending'}, {'active_jobs': 0, 'flow_phase': 'checking'}):
            with self.assertRaisesRegex(RuntimeError, 'ACTIVE_JOB'):
                require_idle(state)

    def test_corrupt_artifact_is_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'image.tar.gz').write_bytes(b'changed')
            write_json(root / 'manifest.json', {'release_id': 'release-test',
                'image': 'organization-directory-runtime:release-test', 'archive_sha256': 'incorrect'})
            with self.assertRaisesRegex(RuntimeError, 'ARCHIVE_HASH_MISMATCH'):
                release.validate_artifact(root)

    def test_failed_switch_restores_previous_image_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host({'root': directory, 'compose': 'compose.yaml', 'project': 'test',
                         'services': ['app', 'mcp'], 'transport': 'local'})
            before = {'schema': 'head', 'active_jobs': 0, 'flow_phase': 'pending',
                      'state': {'initialization_status': 'pending'}, 'counts': {}}
            manifest = {'schema': 'head', 'image': 'new', 'image_id': 'sha256:new', 'release_id': 'release-test'}
            def command(args, **kwargs):
                if args[:3] == ['docker', 'image', 'inspect']:
                    return 'sha256:new'
                if args[:3] == ['docker', 'run', '--rm']:
                    return 'head'
                if args[-1] == '-':
                    return json.dumps(before)
                return ''
            images = {'app': 'sha256:old', 'mcp': 'sha256:old', 'migrate': 'sha256:old'}
            with patch('release_host.run', side_effect=command), patch.object(host, 'probe', return_value=before), \
                 patch.object(host, 'images', return_value=images), patch.object(host, 'up', side_effect=[RuntimeError('failed'), None]), \
                 patch.object(host, 'verify', return_value={'images': images}):
                with self.assertRaisesRegex(RuntimeError, 'DEPLOY_FAILED_ROLLED_BACK'):
                    host.apply(manifest)
            self.assertEqual(json.loads(host.override.read_text())['services']['app']['image'], 'sha256:old')
            self.assertTrue((host.archive_root / 'release-test/rollback-verified.json').exists())
            self.assertFalse((Path(directory) / '.cache/deployment.lock').exists())

    def test_migration_block_happens_before_any_switch_or_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host({'root': directory})
            with patch.object(host, 'probe', return_value={'schema': 'old', 'active_jobs': 0, 'flow_phase': None}), \
                 patch('release_host.run') as command:
                with self.assertRaisesRegex(RuntimeError, 'MIGRATION_REQUIRED'):
                    host.apply({'schema': 'new'})
                command.assert_not_called()
            self.assertFalse(host.archive_root.exists())

    def test_deployment_lock_blocks_concurrent_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host({'root': directory})
            with host.lock():
                with self.assertRaisesRegex(RuntimeError, 'DEPLOYMENT_LOCKED'):
                    with host.lock():
                        self.fail('第二个发布不应进入')

    def test_rollback_failure_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host({'root': directory, 'compose': 'compose.yaml', 'project': 'test', 'services': ['app'], 'transport': 'local'})
            before = {'schema': 'head', 'active_jobs': 0, 'flow_phase': 'pending', 'state': {'initialization_status': 'pending'}}
            manifest = {'schema': 'head', 'image': 'new', 'image_id': 'sha256:new', 'release_id': 'release-test'}
            def command(args, **kwargs):
                return ('sha256:new' if args[:3] == ['docker', 'image', 'inspect'] else 'head'
                        if args[:3] == ['docker', 'run', '--rm'] else json.dumps(before) if args[-1] == '-' else '')
            with patch('release_host.run', side_effect=command), patch.object(host, 'probe', return_value=before), \
                 patch.object(host, 'images', return_value={'app': 'sha256:old'}), \
                 patch.object(host, 'up', side_effect=RuntimeError('failed')):
                with self.assertRaisesRegex(RuntimeError, 'DEPLOY_AND_ROLLBACK_FAILED'):
                    host.apply(manifest)

    def test_cross_migration_image_rollback_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host({'root': directory})
            archive = Path(directory)
            write_json(archive / 'previous-images.json', {'services': {'app': {'image': 'sha256:old'}}})
            write_json(archive / 'before.json', {'schema': '0010_initialization_wizard'})
            with patch('release_host.run', return_value='0009_operation_receipt'), patch.object(host, 'up') as up:
                with self.assertRaisesRegex(RuntimeError, 'MIGRATION_REQUIRED'):
                    host.restore(archive)
                up.assert_not_called()
            self.assertFalse(host.override.exists())


if __name__ == '__main__':
    unittest.main()
