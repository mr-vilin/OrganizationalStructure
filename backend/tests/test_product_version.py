"""版本元信息不得伪造发行状态，也不能绕过管理员认证。"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_admin_identity
from app import version


def test_source_baseline_is_development_and_not_a_database_version():
    info = version.product_build_info()
    assert info['version'] == json.loads((Path(__file__).resolve().parents[2] / 'version.json').read_text(encoding='utf-8'))['version']
    assert info['stage'] == 'development'
    assert info['releaseDate'] is None
    assert 'data_version' not in info


def test_version_endpoint_requires_admin_and_returns_no_store():
    with TestClient(app) as client:
        assert client.get('/admin/api/system/version').status_code == 401
        previous = app.dependency_overrides.get(get_admin_identity)
        app.dependency_overrides[get_admin_identity] = lambda: object()
        try:
            response = client.get('/admin/api/system/version')
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
            assert response.json()['data'] == version.product_build_info()
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_admin_identity, None)
            else:
                app.dependency_overrides[get_admin_identity] = previous


def test_installed_build_metadata_wins_over_source_manifest(tmp_path, monkeypatch):
    built = tmp_path / '_build_info.json'
    data = {'version': '0.2.0-rc.1', 'stage': 'prerelease', 'releaseDate': '2026-10-24',
            'commit': 'b' * 40, 'dirty': False, 'builtAt': '2026-10-24T00:00:00Z'}
    built.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(version, '__file__', str(tmp_path / 'version.py'))
    assert version.product_build_info() == data
