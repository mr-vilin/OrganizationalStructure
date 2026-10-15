from types import SimpleNamespace
from datetime import datetime
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.capabilities.service import OrganizationCapabilities
from app.capabilities.observations import ObservationService
from app.capabilities.receipts import ReceiptRepository
from app.persistence.models import Base, DatasetState, Department, Employee, EmployeeDepartment, StoreProfile, SyncJob, SyncJobDetail, ChangeLog, SystemSetting
from app.persistence.read_service import SqlReadService
from app.persistence.repositories import SqlSyncJobRepository
from app.stores.service import StoreAdminService

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_runtime
from app.main import app


@pytest.fixture
def boundary():
    runtime = Mock()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_service_token='synthetic-service-token', agent_environment='production')
    def resolve_runtime():
        return runtime()
    app.dependency_overrides[get_runtime] = resolve_runtime
    try:
        with TestClient(app) as client:
            yield client, runtime
    finally:
        app.dependency_overrides.clear()


def test_missing_service_token_rejected_before_runtime(boundary):
    client, runtime = boundary
    response = client.get('/internal/capabilities/status')
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AGENT_SERVICE_UNAUTHORIZED'
    runtime.assert_not_called()



@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kwargs):
    return 'INTEGER'


HEADERS = {'Authorization': 'Bearer synthetic-service-token', 'X-Agent-Actor-Type': 'human_agent',
           'X-Agent-Actor-Id': 'agent-a', 'X-Agent-Environment': 'production'}


@pytest.fixture
def http():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.create_collation('utf8mb4_bin', lambda a, b: (a > b) - (a < b))
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as db:
        db.add(DatasetState(id=1, dataset_epoch='epoch', data_version=7, initialization_status='complete', coverage_status='complete'))
        db.add(Department(id='a', feishu_department_id='a', name='门店', sync_quality='complete'))
        db.flush()
        db.add(Employee(id='u', feishu_user_id='u', name='员工', primary_department_id='a', sync_quality='complete'))
        db.flush()
        db.add(EmployeeDepartment(employee_id='u', department_id='a', active=True))
        db.add(StoreProfile(department_id='a', is_store=True, store_code='A', notes='原备注'))
        db.add(SystemSetting(key='task_queue_lock', value='1'))
    capabilities = OrganizationCapabilities(sessions, SqlReadService(sessions, 'synthetic-cursor-key'), StoreAdminService(sessions), SqlSyncJobRepository(sessions), ReceiptRepository(), ObservationService(), environment='production')
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_service_token='synthetic-service-token', agent_environment='production')
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(capabilities=capabilities)
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def apply_body(**updates):
    return {'changes': [{'department_id': 'a', 'is_store': True, 'notes': '新备注'}],
            'expected_epoch': 'epoch', 'expected_version': 7, 'idempotency_key': 'apply-key', **updates}


def test_body_approval_and_actor_cannot_authorize_production_write(http):
    client, _ = http
    response = client.post('/internal/capabilities/stores/batch/apply', headers=HEADERS,
                           json=apply_body(actor_id='forged', approved=True, token='synthetic-secret', approval_token='synthetic-secret'))
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'CONFIRMATION_REQUIRED'
    assert 'synthetic-secret' not in response.text


@pytest.mark.parametrize('path,expected', [
    ('/departments', 'a'), ('/departments/a', 'a'), ('/employees', 'u'),
    ('/employees/u', 'u'), ('/stores', 'a'), ('/stores/a', 'a'),
])
def test_organization_queries_return_capability_result(http, path, expected):
    client, _ = http
    response = client.get('/internal/capabilities' + path, headers=HEADERS)
    assert response.status_code == 200
    result = response.json()
    assert set(result) == {'operation_id', 'data', 'observation', 'audit'}
    data = result['data']['data']
    assert (data[0] if isinstance(data, list) else data)['id'] == expected
    assert result['data']['meta']['dataset_epoch'] == 'epoch'
    assert result['observation']['data_version'] == 7


def test_authorized_apply_and_operation_observation_isolated_by_trusted_actor(http):
    client, _ = http
    headers = {**HEADERS, 'X-Agent-Approved': 'true'}
    body = apply_body(actor_id='forged', actor={'actor_id': 'forged'}, approved=False)
    result = client.post('/internal/capabilities/stores/batch/apply', headers=headers, json=body)
    assert result.status_code == 200
    operation = result.json()
    assert operation['audit']['actor_id'] == 'agent-a'
    replay = client.post('/internal/capabilities/stores/batch/apply', headers=headers, json=body)
    assert replay.status_code == 200
    assert replay.json() == operation
    for suffix in ['/operations/' + operation['operation_id'], '/operations/lookup?idempotency_key=apply-key']:
        found = client.get('/internal/capabilities' + suffix, headers=HEADERS)
        assert found.status_code == 200
        assert found.json() == operation
        hidden = client.get('/internal/capabilities' + suffix, headers={**HEADERS, 'X-Agent-Actor-Id': 'other'})
        assert hidden.status_code == 404
        assert hidden.json()['error']['code'] == 'OPERATION_NOT_FOUND'


def test_sync_request_observe_and_retry_are_capability_operations(http):
    client, sessions = http
    prefix = '/internal/capabilities/sync/jobs'
    headers = {**HEADERS, 'X-Agent-Approved': 'true'}
    denied = client.post(prefix, headers=HEADERS, json={'job_type': 'full', 'idempotency_key': 'sync-key'})
    assert denied.status_code == 409
    assert denied.json()['error']['code'] == 'CONFIRMATION_REQUIRED'
    accepted = client.post(prefix, headers=headers, json={'job_type': 'full', 'idempotency_key': 'sync-key'})
    assert accepted.status_code == 202
    operation = accepted.json()
    job_id = operation['data']['job_id']
    assert operation['data']['status'] == 'accepted'
    observed = client.get(prefix + '/' + job_id, headers=HEADERS)
    assert observed.status_code == 200
    assert observed.json()['data']['status'] == 'queued'
    assert observed.json()['data']['operation_ids'] == [operation['operation_id']]
    hidden = client.get(prefix + '/' + job_id, headers={**HEADERS, 'X-Agent-Actor-Id': 'other'})
    assert hidden.json()['data']['operation_ids'] == []
    assert client.post(prefix + '/' + job_id + '/retry', headers=headers, json={'idempotency_key': 'retry-key'}).status_code == 409
    with sessions.begin() as db:
        job = db.get(SyncJob, job_id)
        job.status, job.error_code, job.error_detail = 'failed', 'REMOTE_ERROR', 'Bearer synthetic-upstream-secret'
    retried = client.post(prefix + '/' + job_id + '/retry', headers=headers, json={'idempotency_key': 'retry-key'})
    assert retried.status_code == 202
    assert retried.json()['data']['job_id'] == job_id
    assert retried.json()['operation_id'] != operation['operation_id']
    assert 'synthetic-upstream-secret' not in retried.text


def test_logs_cursor_snapshot_and_secrets(http):
    client, sessions = http
    with sessions.begin() as db:
        for index in range(3):
            db.add(ChangeLog(object_type='store', object_id='a', source='admin', actor='agent-a',
                             after_data={'notes': 'synthetic-upstream-secret', 'token': 'synthetic-upstream-secret'},
                             committed_at=datetime(2026, 10, 13, 1, index)))
    path = '/internal/capabilities/change-logs'
    params = {'limit': 1, 'actor': 'agent-a', 'committed_after': '2026-10-13T01:00:00Z', 'dataset_epoch': 'epoch', 'data_version': 7}
    first = client.get(path, headers=HEADERS, params=params)
    assert first.status_code == 200
    assert 'synthetic-upstream-secret' not in first.text
    assert first.json()['data']['data'][0]['committed_at'].endswith('+00:00')
    cursor = first.json()['data']['meta']['next_cursor']
    assert isinstance(cursor, str) and not cursor.isdigit()
    second = client.get(path, headers=HEADERS, params={**params, 'cursor': cursor})
    assert second.status_code == 200
    assert second.json()['data']['data'][0]['id'] != first.json()['data']['data'][0]['id']
    invalid = client.get(path, headers=HEADERS, params={**params, 'cursor': cursor, 'actor': 'other'})
    assert invalid.status_code == 400
    assert invalid.json()['error']['code'] == 'INVALID_CURSOR'
    changed = client.get(path, headers=HEADERS, params={**params, 'cursor': cursor, 'dataset_epoch': 'old'})
    assert changed.status_code == 409
    assert changed.json()['error']['code'] == 'DATASET_CHANGED'


@pytest.mark.parametrize('updates', [
    {'Authorization': None}, {'Authorization': ''}, {'Authorization': 'Bearer '},
    {'Authorization': 'Bearer wrong-token'}, {'Authorization': b'Bearer caf\xe9'},
    {'Authorization': 'Basic synthetic-service-token'},
    {'X-Agent-Actor-Type': None}, {'X-Agent-Actor-Type': 'admin'},
    {'X-Agent-Actor-Id': ''}, {'X-Agent-Actor-Id': '   '}, {'X-Agent-Actor-Id': 'a b'},
    {'X-Agent-Actor-Id': 'a' * 192}, {'X-Agent-Environment': None},
    {'X-Agent-Environment': 'test'}, {'X-Agent-Environment': 'staging'},
    {'X-Agent-Approved': '1'}, {'X-Agent-Approved': 'True'}, {'X-Agent-Approved': ''},
    {'X-Agent-Run-Id': ''}, {'X-Agent-Case-Id': 'case with spaces'},
])
def test_invalid_identity_is_uniformly_unauthorized_without_runtime(boundary, updates):
    client, runtime = boundary
    headers = {key: value for key, value in {**HEADERS, **updates}.items() if value is not None}
    response = client.get('/internal/capabilities/status', headers=headers)
    assert response.status_code == 401
    assert response.json() == {'error': {'code': 'AGENT_SERVICE_UNAUTHORIZED', 'message': '内部能力服务身份无效'}}
    assert 'wrong-token' not in response.text
    runtime.assert_not_called()


@pytest.mark.parametrize('configured', [None, '', '  '])
def test_unconfigured_or_empty_token_disables_boundary(boundary, configured):
    client, runtime = boundary
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_service_token=configured)
    response = client.get('/internal/capabilities/status', headers=HEADERS)
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AGENT_SERVICE_UNAUTHORIZED'
    runtime.assert_not_called()


@pytest.mark.parametrize('header', ['Authorization', 'X-Agent-Actor-Id', 'X-Agent-Environment', 'X-Agent-Approved'])
def test_duplicate_trusted_headers_are_rejected(boundary, header):
    client, runtime = boundary
    headers = [(key, value) for key, value in HEADERS.items() if key != header] + [(header, HEADERS.get(header, 'true'))] * 2
    response = client.get('/internal/capabilities/status', headers=headers)
    assert response.status_code == 401
    runtime.assert_not_called()


def test_authenticated_missing_runtime_is_explicit(boundary):
    client, runtime = boundary
    runtime.return_value = None
    response = client.get('/internal/capabilities/status', headers=HEADERS)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'DATABASE_NOT_CONFIGURED'


@pytest.mark.parametrize('method,path', [
    ('GET', '/status'), ('GET', '/departments'), ('GET', '/departments/a'),
    ('GET', '/employees'), ('GET', '/employees/u'), ('GET', '/stores'),
    ('GET', '/stores/a'), ('GET', '/stores/a/employees'), ('GET', '/change-logs'),
    ('GET', '/sync/jobs/j'), ('GET', '/operations/lookup?idempotency_key=k'),
    ('GET', '/operations/op'), ('POST', '/stores/batch/preview'),
    ('POST', '/stores/batch/apply'), ('POST', '/sync/jobs'), ('POST', '/sync/jobs/j/retry'),
])
def test_every_capability_endpoint_is_protected(boundary, method, path):
    client, runtime = boundary
    response = client.request(method, '/internal/capabilities' + path, json={})
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'AGENT_SERVICE_UNAUTHORIZED'
    runtime.assert_not_called()


@pytest.mark.parametrize('updates', [{'expected_epoch': 'old'}, {'expected_version': 6}])
def test_apply_stale_epoch_or_version_is_conflict(http, updates):
    client, _ = http
    response = client.post('/internal/capabilities/stores/batch/apply', headers={**HEADERS, 'X-Agent-Approved': 'true'}, json=apply_body(**updates))
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DATASET_CHANGED'


@pytest.mark.parametrize('field,value,missing', [
    ('expected_epoch', None, True), ('expected_version', None, True),
    ('expected_epoch', None, False), ('expected_version', True, False),
    ('expected_version', -1, False), ('expected_epoch', '', False),
])
def test_apply_requires_explicit_valid_epoch_and_version(http, field, value, missing):
    client, _ = http
    body = apply_body(**{field: value})
    if missing:
        del body[field]
    response = client.post('/internal/capabilities/stores/batch/apply', headers={**HEADERS, 'X-Agent-Approved': 'true'}, json=body)
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'


def test_patch_omission_and_null_survive_transport_and_conflict_with_same_key(http):
    client, _ = http
    headers = {**HEADERS, 'X-Agent-Approved': 'true'}
    preview = client.post('/internal/capabilities/stores/batch/preview', headers=HEADERS, json=apply_body())
    assert preview.status_code == 200
    assert client.get('/internal/capabilities/status', headers=HEADERS).json()['observation']['data_version'] == 7
    first = client.post('/internal/capabilities/stores/batch/apply', headers=headers, json=apply_body())
    assert first.status_code == 200
    stored = client.get('/internal/capabilities/stores/a', headers=HEADERS).json()['data']['data']
    assert stored['store_code'] == 'A' and stored['notes'] == '新备注'
    clear = [{'department_id': 'a', 'is_store': True, 'store_code': None, 'notes': None}]
    conflict = client.post('/internal/capabilities/stores/batch/apply', headers=headers, json=apply_body(changes=clear))
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'OPERATION_CONFLICT'
    second = client.post('/internal/capabilities/stores/batch/apply', headers=headers,
                         json=apply_body(changes=clear, expected_version=8, idempotency_key='clear-key'))
    assert second.status_code == 200
    stored = client.get('/internal/capabilities/stores/a', headers=HEADERS).json()['data']['data']
    assert stored['store_code'] is None and stored['notes'] is None


def test_historical_idempotent_replay_keeps_original_receipt(http):
    client, sessions = http
    headers = {**HEADERS, 'X-Agent-Approved': 'true'}
    first = client.post('/internal/capabilities/stores/batch/apply', headers=headers, json=apply_body()).json()
    with sessions.begin() as db:
        db.get(DatasetState, 1).dataset_epoch = 'restored-epoch'
    replay = client.post('/internal/capabilities/stores/batch/apply', headers=headers, json=apply_body())
    assert replay.status_code == 200
    historical = replay.json()
    assert historical['operation_id'] == first['operation_id']
    assert historical['data'] == first['data']
    assert historical['audit'] == first['audit']
    assert historical['observation']['dataset_epoch'] == 'epoch'
    assert historical['observation']['execution'] == 'unconfirmed'
    assert historical['observation']['evidence']['current_dataset_epoch'] == 'restored-epoch'


def test_store_membership_and_department_find_filters(http):
    client, _ = http
    assert client.post('/internal/capabilities/stores/batch/apply', headers={**HEADERS, 'X-Agent-Approved': 'true'}, json=apply_body()).status_code == 200
    employees = client.get('/internal/capabilities/stores/a/employees', headers=HEADERS, params={'membership': 'primary'})
    assert employees.status_code == 200
    assert [item['id'] for item in employees.json()['data']['data']] == ['u']
    for params in [{'department_id': 'a'}, {'name': '门店'}, {'path': '门店'}]:
        found = client.get('/internal/capabilities/departments', headers=HEADERS, params=params)
        assert found.status_code == 200
        assert [item['id'] for item in found.json()['data']['data']] == ['a']


def test_job_and_error_responses_filter_secrets(http, monkeypatch):
    client, sessions = http
    with sessions.begin() as db:
        db.add(SyncJob(id='failed', type='full', requested_by='agent-a', status='failed', error_code='REMOTE_ERROR',
                       error_detail='Bearer synthetic-upstream-secret', created_at=datetime.now(), updated_at=datetime.now()))
        db.flush()
        db.add(SyncJobDetail(job_id='failed', object_type='employee', object_id='u', status='failed', error_code='Bearer synthetic-upstream-secret'))
    response = client.get('/internal/capabilities/sync/jobs/failed', headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['data']['error_code'] == 'REMOTE_ERROR'
    assert response.json()['data']['details'][0]['error_code'] is None
    assert 'synthetic-upstream-secret' not in response.text
    from app.capabilities.errors import CapabilityUnavailable
    def unavailable(*args):
        raise CapabilityUnavailable('Bearer synthetic-upstream-secret')
    monkeypatch.setattr(OrganizationCapabilities, 'status', unavailable)
    failed = client.get('/internal/capabilities/status', headers=HEADERS)
    assert failed.status_code == 503
    assert failed.json()['error']['code'] == 'CAPABILITY_UNAVAILABLE'
    assert 'synthetic-upstream-secret' not in failed.text


def test_auth_validation_does_not_echo_body_secrets(http):
    client, _ = http
    response = client.post('/internal/capabilities/stores/batch/apply', headers=HEADERS,
                           json=apply_body(expected_version='synthetic-body-secret', token='synthetic-body-secret'))
    assert response.status_code == 422
    assert 'synthetic-body-secret' not in response.text


def test_admin_cookie_and_public_credentials_do_not_replace_service_token(boundary):
    client, runtime = boundary
    for headers in [{'Authorization': 'Bearer client.secret'}, {'Cookie': 'org_session=synthetic-session; org_csrf=synthetic-csrf'}]:
        response = client.get('/internal/capabilities/status', headers={**HEADERS, 'Authorization': '', **headers})
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'AGENT_SERVICE_UNAUTHORIZED'
    runtime.assert_not_called()
    runtime.return_value = None
    assert client.get('/api/v1/status', headers=HEADERS).json()['error']['code'] == 'UNAUTHORIZED'
    assert client.post('/admin/api/sync/jobs', headers=HEADERS, json={'type': 'full'}).json()['error']['code'] == 'ADMIN_SESSION_REQUIRED'


def test_test_ci_requires_safe_run_id_and_context_environment(http):
    client, sessions = http
    runtime = SimpleNamespace(capabilities=OrganizationCapabilities(sessions, SqlReadService(sessions, 'synthetic-cursor-key'), StoreAdminService(sessions), SqlSyncJobRepository(sessions), ReceiptRepository(), ObservationService(), environment='test'))
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_service_token='synthetic-service-token', agent_environment='test')
    headers = {**HEADERS, 'X-Agent-Environment': 'test', 'X-Agent-Actor-Type': 'ci_agent'}
    denied = client.get('/internal/capabilities/status', headers=headers)
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'CAPABILITY_NOT_ALLOWED'
    accepted = client.post('/internal/capabilities/stores/batch/apply', headers={**headers, 'X-Agent-Run-Id': 'test-run', 'X-Agent-Case-Id': 'case-1'}, json=apply_body())
    assert accepted.status_code == 200
    assert accepted.json()['audit']['environment'] == 'test'
    assert accepted.json()['audit']['actor_id'] == 'agent-a'


def test_production_ci_is_not_authorized_even_with_confirmation(http):
    client, _ = http
    response = client.get('/internal/capabilities/status', headers={**HEADERS, 'X-Agent-Actor-Type': 'ci_agent', 'X-Agent-Run-Id': 'test-run', 'X-Agent-Approved': 'true'})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'CAPABILITY_NOT_ALLOWED'


def test_department_ambiguity_keeps_stable_candidates(http):
    client, sessions = http
    with sessions.begin() as db:
        db.add(Department(id='b', feishu_department_id='b', name='门店', sync_quality='complete'))
    response = client.get('/internal/capabilities/departments', headers=HEADERS, params={'name': '门店'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'AMBIGUOUS_TARGET'
    assert {item['id'] for item in response.json()['error']['candidates']} == {'a', 'b'}
    assert set(response.json()['error']['candidates'][0]) == {'id', 'name', 'path', 'status'}

@pytest.mark.parametrize('params,status,code', [
    ({'data_version': 6}, 409, 'DATASET_CHANGED'),
    ({'cursor': '1'}, 400, 'INVALID_CURSOR'),
    ({'committed_after': '2026-10-13T01:00:00'}, 422, 'INVALID_CAPABILITY_REQUEST'),
])
def test_log_snapshot_and_cursor_errors_cross_http_unchanged(http, params, status, code):
    client, _ = http
    response = client.get('/internal/capabilities/change-logs', headers=HEADERS, params=params)
    assert response.status_code == status
    assert response.json()['error']['code'] == code
