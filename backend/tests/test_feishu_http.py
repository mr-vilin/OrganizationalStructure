import hashlib
import hmac
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings, Settings
from app.dependencies import get_admin_identity, get_runtime


def test_session_bootstrap_requires_matching_cookie_and_does_not_put_csrf_in_url(sqlite_sessions):
    secret='s'*32
    app.dependency_overrides[get_settings]=lambda: Settings(session_secret=secret)
    app.dependency_overrides[get_admin_identity]=lambda: SimpleNamespace(open_id='ou',csrf_hash=hmac.new(secret.encode(),b'csrf',hashlib.sha256).hexdigest())
    app.dependency_overrides[get_runtime]=lambda: SimpleNamespace(sessions=sqlite_sessions)
    try:
        client=TestClient(app)
        assert client.get('/admin/auth/session').status_code == 403
        client.cookies.set('org_csrf','csrf')
        response=client.get('/admin/auth/session')
        assert response.json() == {'data':{'open_id':'ou','csrf_token':'csrf','initialization_complete':True},'meta':{}}
        assert response.headers['cache-control'] == 'no-store'
    finally: app.dependency_overrides.clear()


def test_schedule_routes_and_login_unconfigured_are_safe():
    client=TestClient(app)
    assert client.get('/admin/auth/login').status_code == 503
    assert client.get('/admin/api/settings/reconcile-schedule').status_code == 401
    assert client.put('/admin/api/settings/reconcile-schedule',json={}).status_code == 401


def test_connection_unknown_is_degraded_and_secret_is_never_echoed():
    from app.feishu.health import connection_summary
    settings=Settings(feishu_app_id='cli_sensitive',feishu_app_secret='NEVER-ECHO',feishu_tenant_key='tenant_sensitive')
    result=connection_summary(settings,None)
    assert result['status']=='degraded'
    assert 'NEVER-ECHO' not in str(result)
    assert result['app_id_masked'] != 'cli_sensitive'
