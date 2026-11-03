"""固定发布入口：默认本地，远端写入必须显式指定环境和人工授权说明。"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy'))
from release_host import Host, run


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def image_config_id(archive, image):
    """从 Docker 导出包读取配置摘要，兼容两种镜像存储引擎的 ID 表示。"""
    with tarfile.open(archive, 'r:*') as bundle:
        with bundle.extractfile('manifest.json') as stream:
            entries = [entry for entry in json.load(stream) if image in (entry.get('RepoTags') or [])]
        if len(entries) != 1:
            raise RuntimeError('IMAGE_ARCHIVE_TAG_MISMATCH')
        with bundle.extractfile(entries[0]['Config']) as stream:
            return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def environment(name, action, authorization):
    target = json.loads((ROOT / 'deploy/environments.json').read_text(encoding='utf-8'))[name]
    if not target['configured']:
        raise RuntimeError('ENVIRONMENT_NOT_CONFIGURED: 正式环境尚未建立，不得使用测试环境替代')
    if name != 'local' and action in ('deploy', 'rollback') and not authorization.strip():
        raise RuntimeError('REMOTE_AUTHORIZATION_REQUIRED: 必须有用户当次明确部署该环境的指令')
    target['environment'] = name
    if authorization:
        target['authorization'] = authorization
    if name == 'local':
        target['root'] = str(ROOT)
    return target


def build(release_tag=None):
    run(['node', 'scripts/versioning.mjs', 'check', *(['--release', '--tag', release_tag] if release_tag else [])], cwd=ROOT)
    commit = run(['git', 'rev-parse', 'HEAD'], cwd=ROOT).strip()
    dirty = bool(run(['git', 'status', '--porcelain'], cwd=ROOT).strip())
    if release_tag:
        if dirty or run(['git', 'rev-list', '-n', '1', release_tag], cwd=ROOT).strip() != commit:
            raise RuntimeError('RELEASE_REQUIRES_CLEAN_TAGGED_HEAD')
    release_id = datetime.now(timezone.utc).strftime('release-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    out = ROOT / '.cache' / 'artifacts' / release_id
    source = out / 'source'
    source.mkdir(parents=True)
    names = run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).split('\0')
    files = {}
    for name in sorted(set(names)):
        if not name or not (name.startswith(('backend/', 'frontend/', 'deploy/', 'scripts/'))
                            or name in ('Dockerfile', '.dockerignore', 'version.json', 'CHANGELOG.md')):
            continue
        path = ROOT / name
        if not path.exists():
            continue  # 已删除的受控文件不进入快照。
        if path.is_symlink() or any(part.startswith('.env') for part in Path(name).parts):
            raise RuntimeError('UNSAFE_SOURCE_PATH: ' + name)
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        files[name] = digest(destination)
    schema_text = (source / 'backend/app/persistence/database.py').read_text(encoding='utf-8')
    schema = re.search(r'CURRENT_SCHEMA_HEAD\s*=\s*[\'"]([^\'"]+)', schema_text).group(1)
    # 保持仓库 Dockerfile 单一来源；仅替换已登记的官方镜像地址与固定摘要。
    bases = json.loads((ROOT / 'deploy/build-images.json').read_text(encoding='utf-8'))
    dockerfile = (source / 'Dockerfile').read_text(encoding='utf-8')
    for original, pinned in bases.items():
        if 'FROM ' + original + ' ' not in dockerfile:
            raise RuntimeError('BASE_IMAGE_CONFIGURATION_STALE')
        dockerfile = dockerfile.replace('FROM ' + original + ' ', 'FROM ' + pinned + ' ')
    (source / 'Dockerfile.release').write_text(dockerfile, encoding='utf-8')
    image = 'organization-directory-runtime:' + release_id
    command = ['docker', 'build', '-f', str(source / 'Dockerfile.release'), '--build-arg', 'ORG_COMMIT_SHA=' + commit,
               '--build-arg', 'ORG_SOURCE_DIRTY=' + str(dirty).lower(), '-t', image]
    if release_tag:
        command += ['--build-arg', 'ORG_RELEASE_TAG=' + release_tag]
    print('正在构建 ' + image, flush=True)
    # 构建上下文没有凭据，保留构建进度和原始退出码。
    subprocess.run(command + [str(source)], cwd=ROOT, check=True)
    image_id = run(['docker', 'image', 'inspect', image, '--format', '{{.Id}}']).strip()
    info = json.loads(run(['docker', 'run', '--rm', '--network', 'none', image, 'python', '-c',
                          'import json; from app.version import product_build_info; print(json.dumps(product_build_info()))']))
    archive = out / 'image.tar'
    run(['docker', 'save', '-o', str(archive), image])
    config_id = image_config_id(archive, image)
    compressed = out / 'image.tar.gz'
    with archive.open('rb') as src, gzip.open(compressed, 'wb', compresslevel=1) as dst:
        shutil.copyfileobj(src, dst)
    archive.unlink()
    manifest = {'release_id': release_id, 'image': image, 'image_id': image_id, 'image_config_id': config_id, 'commit': commit,
                'dirty': dirty, 'release_tag': release_tag, 'schema': schema, 'build': info,
                'files': files, 'build_images': bases, 'archive_sha256': digest(compressed)}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def ssh(target, command, data=None):
    return run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', target['ssh_host'], command], data=data)


def remote_read(target, action):
    # 只读检查直接通过 stdin 执行，不上传文件，不修改远端部署配置。
    code = (ROOT / 'deploy/release_host.py').read_text(encoding='utf-8').split("if __name__ == '__main__':")[0]
    probe = (ROOT / 'deploy/release_probe.py').read_text(encoding='utf-8')
    code = code.replace("Path(__file__).with_name('release_probe.py').read_text(encoding='utf-8')", repr(probe))
    expression = "host.probe('snapshot()')" if action == 'inspect' else 'host.verify()'
    code += '\nhost = Host(' + repr(target) + ')\nresult = ' + expression
    code += "\nif 'assets' in result: result['assets'] = len(result['assets'])\nprint(json.dumps(result, ensure_ascii=False))"
    return json.loads(ssh(target, 'sudo -n python3 -', code))


def validate_artifact(path):
    manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'release-[a-z0-9-]+', manifest['release_id']):
        raise RuntimeError('INVALID_RELEASE_ID')
    if manifest['image'] != 'organization-directory-runtime:' + manifest['release_id']:
        raise RuntimeError('INVALID_IMAGE_NAME')
    if digest(path / 'image.tar.gz') != manifest['archive_sha256']:
        raise RuntimeError('ARCHIVE_HASH_MISMATCH')
    return manifest


def remote_write(target, action, artifact, manifest, release_id, authorization):
    token = 'org-release-' + uuid.uuid4().hex
    remote = '/tmp/' + token
    ssh(target, 'umask 077 && mkdir ' + remote)
    staging = ROOT / '.cache' / token
    staging.mkdir()
    (staging / 'target.json').write_text(json.dumps(target), encoding='utf-8')
    files = [ROOT / 'deploy/release_host.py', ROOT / 'deploy/release_probe.py', staging / 'target.json']
    if action == 'deploy':
        files += [artifact / 'manifest.json', artifact / 'image.tar.gz']
    run(['scp', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', *map(str, files), target['ssh_host'] + ':' + remote + '/'])
    command = 'sudo -n python3 ' + remote + '/release_host.py '
    if action == 'deploy':
        # 校验上传字节后才导入镜像和切换。
        check = 'import hashlib; from pathlib import Path; p=Path(' + repr(remote + '/image.tar.gz') + '); assert hashlib.sha256(p.read_bytes()).hexdigest() == ' + repr(manifest['archive_sha256'])
        ssh(target, 'python3 -c ' + shlex.quote(check))
        ssh(target, 'sudo -n docker load -i ' + remote + '/image.tar.gz')
        command += 'apply ' + remote + '/target.json --manifest ' + remote + '/manifest.json'
    else:
        command += 'rollback ' + remote + '/target.json --release-id ' + shlex.quote(release_id)
    result = json.loads(ssh(target, command))
    (staging / 'result.json').write_text(json.dumps({'authorization': authorization, 'target': target, 'result': result}, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'inspect', 'build', 'deploy', 'verify', 'rollback'])
    parser.add_argument('--environment', choices=['local', 'test', 'production'], default='local')
    parser.add_argument('--artifact', type=Path, help='已有构建制品目录，含 manifest.json 和 image.tar.gz')
    parser.add_argument('--authorization', default='', help='记录用户本次明确的远端部署指令，不是自动授权开关')
    parser.add_argument('--release-tag')
    parser.add_argument('--release-id')
    args = parser.parse_args()
    target = environment(args.environment, args.action, args.authorization)
    if args.action == 'plan':
        result = {'target': target, 'migration': '禁止自动执行', 'remote_write': False}
    elif args.action == 'build':
        result = {'artifact': str(build(args.release_tag))}
    elif args.action in ('inspect', 'verify'):
        if target['transport'] == 'ssh':
            result = remote_read(target, args.action)
        else:
            host = Host(target)
            result = host.probe('snapshot()') if args.action == 'inspect' else host.verify()
            if 'assets' in result:
                result['assets'] = len(result['assets'])
    elif args.action == 'deploy':
        if args.environment != 'local' and not args.artifact:
            raise RuntimeError('REMOTE_REQUIRES_REVIEWED_ARTIFACT: 远端必须明确指定已验收制品')
        artifact = args.artifact.resolve() if args.artifact else build(args.release_tag)
        manifest = validate_artifact(artifact)
        if args.environment == 'production':
            receipt = artifact / 'test-deployment.json'
            if manifest['dirty'] or not manifest.get('release_tag') or not receipt.exists():
                raise RuntimeError('PRODUCTION_REQUIRES_TESTED_RELEASE')
            if json.loads(receipt.read_text())['image_id'] != manifest['image_id']:
                raise RuntimeError('TEST_RECEIPT_MISMATCH')
        if target['transport'] == 'ssh':
            result = remote_write(target, args.action, artifact, manifest, None, args.authorization)
        else:
            run(['docker', 'load', '-i', str(artifact / 'image.tar.gz')])
            result = Host(target).apply(manifest)
        (artifact / (args.environment + '-deployment.json')).write_text(json.dumps({
            'image_id': manifest['image_id'], 'authorization': args.authorization, 'result': result}, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        if not args.release_id or not re.fullmatch(r'release-[a-z0-9-]+', args.release_id):
            raise RuntimeError('INVALID_RELEASE_ID')
        if target['transport'] == 'ssh':
            result = remote_write(target, args.action, None, None, args.release_id, args.authorization)
        else:
            host = Host(target)
            result = host.rollback(args.release_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else 'RELEASE_FAILED: 请检查工具与环境，未确认发布完成', file=sys.stderr)
        sys.exit(1)
