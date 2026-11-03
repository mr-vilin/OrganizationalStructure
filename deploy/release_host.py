"""本地／SSH 主机共用的发布执行器；只做无迁移镜像切换。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager


def run(args, *, cwd=None, data=None):
    result = subprocess.run(args, input=data, cwd=cwd, capture_output=True, encoding='utf-8')
    if result.returncode:
        # Docker/Compose 错误可能包含环境变量，默认不转储原始输出。
        raise RuntimeError(f'COMMAND_FAILED: {args[0]} (exit={result.returncode})')
    return result.stdout


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def require_idle(state):
    if state['active_jobs'] or state['flow_phase'] in ('running', 'checking'):
        raise RuntimeError('ACTIVE_JOB: 等待初始化或同步结束后再发布')


def require_schema(before, expected):
    if before['schema'] != expected:
        raise RuntimeError(f"MIGRATION_REQUIRED: 当前 {before['schema']}，镜像要求 {expected}；先按迁移手册授权执行")


class Host:
    def __init__(self, target):
        self.target = target
        self.root = Path(target['root']).resolve()
        self.override = self.root / '.cache' / 'deployment-image.json'
        self.archive_root = self.root / '.cache' / 'releases'

    @contextmanager
    def lock(self):
        lock = self.root / '.cache' / 'deployment.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock.mkdir()
        except FileExistsError:
            raise RuntimeError('DEPLOYMENT_LOCKED: 已有发布，或前次异常中断；核实进程后人工处理锁目录') from None
        try:
            yield
        finally:
            lock.rmdir()

    def dc(self, override=None):
        command = ['docker', 'compose', '--project-directory', str(self.root), '-p', self.target['project'],
                   '-f', str(self.root / self.target['compose'])]
        candidate = override or self.override
        if candidate.exists():
            command += ['-f', str(candidate)]
        return command + ['--profile', 'agent']

    def probe(self, expression):
        source = Path(__file__).with_name('release_probe.py').read_text(encoding='utf-8')
        source += '\nprint(json.dumps(' + expression + ', ensure_ascii=False))\n'
        running = run(self.dc() + ['ps', '-q', 'app'], cwd=self.root).strip()
        command = (['exec', '-T', 'app', 'python', '-'] if running else
                   ['run', '--rm', '--no-deps', '-T', 'app', 'python', '-'])
        return json.loads(run(self.dc() + command, cwd=self.root, data=source))

    def images(self):
        values = {}
        for service in self.target['services']:
            cid = run(self.dc() + ['ps', '-a', '-q', service], cwd=self.root).strip()
            if not cid or '\n' in cid:
                raise RuntimeError('SERVICE_NOT_RUNNING: ' + service)
            values[service] = run(['docker', 'inspect', cid, '--format', '{{.Image}}']).strip()
        values['migrate'] = values['app']
        return values

    def verify(self, expected_image=None):
        images = self.images()
        if expected_image and any(image != expected_image for image in images.values()):
            raise RuntimeError('RUNNING_IMAGE_MISMATCH')
        for service in self.target['services']:
            cid = run(self.dc() + ['ps', '-q', service], cwd=self.root).strip()
            health = json.loads(run(['docker', 'inspect', cid, '--format', '{{json .State.Health}}']))
            if not health or health['Status'] != 'healthy':
                raise RuntimeError('SERVICE_UNHEALTHY: ' + service)
        # 本地容器内回环检查应用；远端通过正式 HTTPS 反代检查全部资源。
        url = 'http://127.0.0.1:8000' if self.target['transport'] == 'local' else self.target['base_url']
        result = self.probe('verify(' + repr(url) + ')')
        if self.target['transport'] == 'local':
            from urllib.request import ProxyHandler, build_opener
            opener = build_opener(ProxyHandler({}))
            for path in ('/initialize', '/health/ready'):
                with opener.open(self.target['base_url'] + path, timeout=15) as response:
                    if response.status != 200:
                        raise RuntimeError('LOCAL_PUBLISHED_PORT_UNAVAILABLE')
            with opener.open(self.target['base_url'] + '/build-info.json', timeout=15) as response:
                if json.load(response) != result['build']:
                    raise RuntimeError('LOCAL_PUBLISHED_BUILD_MISMATCH')
        result['images'] = images
        return result

    @staticmethod
    def image_config(images):
        return {'services': {name: {'image': image} for name, image in images.items()}}

    def up(self):
        run(self.dc() + ['up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '120',
                         *self.target['services']], cwd=self.root)

    def check_restore(self, archive):
        previous_config = json.loads((archive / 'previous-images.json').read_text(encoding='utf-8'))
        previous_image = previous_config['services']['app']['image']
        previous_schema = run(['docker', 'run', '--rm', '--network', 'none', previous_image, 'python', '-c',
                              'from app.persistence.database import CURRENT_SCHEMA_HEAD; print(CURRENT_SCHEMA_HEAD)']).strip()
        expected = json.loads((archive / 'before.json').read_text(encoding='utf-8'))['schema']
        require_schema({'schema': expected}, previous_schema)
        return previous_config

    def restore(self, archive):
        previous_config = self.check_restore(archive)
        write_json(self.override, previous_config)
        self.up()
        evidence = self.verify()
        previous = json.loads((archive / 'previous-images.json').read_text(encoding='utf-8'))['services']
        if any(evidence['images'][name] != config['image'] for name, config in previous.items()):
            raise RuntimeError('ROLLBACK_IMAGE_MISMATCH')
        previous_source = archive / 'previous-source.json'
        current_source = self.root / '.cache' / 'deployment-source.json'
        if previous_source.exists():
            write_json(current_source, json.loads(previous_source.read_text(encoding='utf-8')))
        elif current_source.exists():
            current_source.unlink()
        write_json(archive / 'rollback-verified.json', evidence)

    def apply(self, manifest):
        with self.lock():
            return self._apply(manifest)

    def _apply(self, manifest):
        before = self.probe('snapshot()')
        require_idle(before)
        require_schema(before, manifest['schema'])
        if self.target.get('environment') == 'production' and (manifest['dirty'] or not manifest.get('release_tag')):
            raise RuntimeError('PRODUCTION_REQUIRES_RELEASE')
        image_id = run(['docker', 'image', 'inspect', manifest['image'], '--format', '{{.Id}}']).strip()
        if image_id != manifest['image_id']:
            raise RuntimeError('IMAGE_ID_MISMATCH')
        archive = self.archive_root / manifest['release_id']
        archive.mkdir(parents=True, exist_ok=False)
        write_json(archive / 'previous-images.json', self.image_config(self.images()))
        write_json(archive / 'before.json', before)
        write_json(archive / 'manifest.json', manifest)
        write_json(archive / 'target.json', self.target)
        previous_source = self.root / '.cache' / 'deployment-source.json'
        if previous_source.exists():
            write_json(archive / 'previous-source.json', json.loads(previous_source.read_text(encoding='utf-8')))
        candidate = archive / 'candidate.json'
        write_json(candidate, self.image_config({name: image_id for name in ('app', 'mcp', 'migrate')}))
        run(self.dc(candidate) + ['config', '--quiet'], cwd=self.root)
        # 用新镜像与真实应用会话做只读 schema 检查；禁止自动 upgrade head。
        check = ('from app.config import get_settings; '
                 'from app.persistence.database import create_mysql_engine,database_ready; '
                 'database_ready(create_mysql_engine(get_settings().database_url))')
        run(self.dc(candidate) + ['run', '--rm', '--no-deps', '-T', 'app', 'python', '-c', check], cwd=self.root)
        try:
            # 停止写入方后再复查，避免预检与切换之间启动任务。
            run(self.dc() + ['stop', *self.target['services']], cwd=self.root)
            source = Path(__file__).with_name('release_probe.py').read_text(encoding='utf-8')
            stopped = json.loads(run(self.dc(candidate) + ['run', '--rm', '--no-deps', '-T', 'app', 'python', '-'],
                                     cwd=self.root, data=source + '\nprint(json.dumps(snapshot()))'))
            require_idle(stopped)
            write_json(self.override, json.loads(candidate.read_text(encoding='utf-8')))
            self.up()
            after = self.probe('snapshot()')
            require_schema(after, before['schema'])
            evidence = self.verify(image_id)
            if evidence['build'] != manifest['build']:
                raise RuntimeError('ARTIFACT_BUILD_MISMATCH')
            # 完成初始化的环境监听器可能正常排队核对，不要求运行中业务数据静止。
            if before['state']['initialization_status'] != 'complete':
                for key in ('state', 'counts', 'flow_phase'):
                    if stopped[key] != after[key]:
                        raise RuntimeError('UNEXPECTED_STATE_CHANGE: ' + key)
            write_json(archive / 'after.json', after)
            write_json(archive / 'verification.json', evidence)
            write_json(self.root / '.cache' / 'deployment-source.json', manifest)
            return {'status': 'deployed', 'archive': str(archive), 'build': after['build'], 'assets': len(evidence['assets'])}
        except Exception:
            try:
                self.restore(archive)
            except Exception:
                raise RuntimeError('DEPLOY_AND_ROLLBACK_FAILED: 请按回退目录人工恢复并验证，不能宣称已回退') from None
            raise RuntimeError('DEPLOY_FAILED_ROLLED_BACK: 已恢复旧镜像，见回退验证文件') from None

    def rollback(self, release_id):
        with self.lock():
            archive = self.archive_root / release_id
            current = self.probe('snapshot()')
            require_idle(current)
            require_schema(current, json.loads((archive / 'before.json').read_text())['schema'])
            # 仅允许回退当前发布，防止误选过旧目录。
            current_source = self.root / '.cache' / 'deployment-source.json'
            if not current_source.exists() or json.loads(current_source.read_text(encoding='utf-8'))['release_id'] != release_id:
                raise RuntimeError('ROLLBACK_NOT_CURRENT_RELEASE')
            self.check_restore(archive)
            run(self.dc() + ['stop', *self.target['services']], cwd=self.root)
            self.restore(archive)
            return {'status': 'rolled_back', 'archive': str(archive)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'verify', 'apply', 'rollback'])
    parser.add_argument('target')
    parser.add_argument('--manifest')
    parser.add_argument('--release-id')
    args = parser.parse_args()
    os.umask(0o077)
    host = Host(json.loads(Path(args.target).read_text(encoding='utf-8')))
    if args.action == 'inspect':
        result = host.probe('snapshot()')
    elif args.action == 'verify':
        result = host.verify()
        result['assets'] = len(result['assets'])
    elif args.action == 'apply':
        result = host.apply(json.loads(Path(args.manifest).read_text(encoding='utf-8')))
    else:
        import re
        if not args.release_id or not re.fullmatch(r'[a-z0-9-]+', args.release_id):
            raise RuntimeError('INVALID_RELEASE_ID')
        result = host.rollback(args.release_id)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else 'RELEASE_HOST_FAILED', file=sys.stderr)
        sys.exit(1)
