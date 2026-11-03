"""在应用容器内执行的只读发布检查，不输出凭据或人员资料。"""
import hashlib
import json
from pathlib import Path


def snapshot():
    from sqlalchemy import text
    from app.config import get_settings
    from app.persistence.database import create_mysql_engine
    from app.version import product_build_info
    with create_mysql_engine(get_settings().database_url).connect() as conn:
        conn.exec_driver_sql('SET TRANSACTION READ ONLY')
        result = {
            'schema': conn.scalar(text('SELECT version_num FROM alembic_version')),
            'state': dict(conn.execute(text('SELECT dataset_epoch,data_version,initialization_status,coverage_status FROM dataset_state WHERE id=1')).mappings().one()),
            'active_jobs': conn.scalar(text("SELECT COUNT(*) FROM sync_job WHERE status IN ('queued','running')")),
            'counts': {table: conn.scalar(text('SELECT COUNT(*) FROM ' + table))
                       for table in ('department', 'employee', 'employee_department', 'store_profile', 'admin_allowlist')},
        }
        value = conn.scalar(text("SELECT value FROM system_setting WHERE `key`='initialization_flow'"))
        result['flow_phase'] = json.loads(value).get('phase') if value else None
        result['build'] = product_build_info()
        return result


def verify(base_url):
    import httpx
    from app.version import product_build_info
    root = Path('/srv/frontend/dist')
    with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
        statuses = {}
        for path, expected in [('/', 200), ('/initialize', 200), ('/health/live', 200),
                               ('/health/ready', 200), ('/admin/auth/session', 401),
                               ('/admin/api/initialization', 401)]:
            response = client.get(base_url + path)
            if response.status_code != expected:
                raise RuntimeError('HTTP_CHECK_FAILED: ' + path)
            statuses[path] = expected
        build = client.get(base_url + '/build-info.json').json()
        if build != product_build_info() or build != json.loads((root / 'build-info.json').read_text()):
            raise RuntimeError('BUILD_MISMATCH')
        assets = []
        for path in sorted(root.rglob('*')):
            if path.suffix not in ('.js', '.css'):
                continue
            relative = path.relative_to(root).as_posix()
            response = client.get(base_url + '/' + relative)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != digest:
                raise RuntimeError('ASSET_MISMATCH: ' + relative)
            assets.append({'path': relative, 'sha256': digest})
        if not assets:
            raise RuntimeError('NO_ASSETS')
        if base_url.startswith('https://'):
            from urllib.parse import parse_qs, urlsplit
            for path in ('/internal', '/internal/capabilities'):
                if client.get(base_url + path).status_code != 404:
                    raise RuntimeError('INTERNAL_ROUTE_EXPOSED')
            login = client.get(base_url + '/admin/auth/login')
            target = urlsplit(login.headers.get('location', ''))
            if (login.status_code != 302 or target.scheme != 'https' or target.hostname != 'open.feishu.cn'
                    or parse_qs(target.query).get('redirect_uri') != [base_url + '/admin/auth/callback']):
                raise RuntimeError('OAUTH_CALLBACK_MISMATCH')
            cookie = login.headers.get('set-cookie', '').lower()
            if not all(part in cookie for part in ('secure', 'httponly', 'samesite=lax')):
                raise RuntimeError('OAUTH_COOKIE_INVALID')
        return {'statuses': statuses, 'build': build, 'assets': assets}
