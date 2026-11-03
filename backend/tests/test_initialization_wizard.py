"""使用真实服务、队列和发布事务验证初始化门禁及失败重来。"""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.config import Settings, get_settings
from app.dependencies import get_runtime
from app.initialization.router import get_initialization_service
from app.initialization.service import InitializationService, load_flow, save_flow, utcnow
from app.initialization.validation import InitializationFailure
from app.main import app
from app.persistence.models import (
    AdminAllowlist, ChangeLog, DatasetState, Department, Employee, EmployeeDepartment,
    EmployeeStore, EventInbox, FeishuConnection, StoreCodeReservation, StoreProfile, SyncJob,
    SystemSetting, WorkerLease,
)
from app.persistence.repositories import SqlIdentityRepository, SqlSyncJobRepository
from app.sync.collector import Candidate, Collector
from app.sync.publisher import Publisher
from app.sync.worker import Worker


MAPPINGS = {'permission_role': 'role', 'store_attribute': 'store', 'employee_type_options': {'1': '正式员工'}}


class Feishu:
    def __init__(self):
        self.departments = {'d': {'open_department_id': 'd', 'parent_department_id': '0', 'name': '部门', 'leader_user_id': None, 'status': {'is_deleted': False}}}
        self.users = {identifier: {'user_id': identifier, 'name': identifier, 'employee_no': None, 'job_title': None,
            'leader_user_id': None, 'employee_type': 1, 'status': {'is_resigned': False},
            'department_ids': ['d'],
            'orders': [{'department_id': 'd', 'is_primary_dept': True}],
            'custom_attrs': [{'id': 'role', 'type': 'ENUMERATION', 'value': {'option_id': 'manager', 'option_value': '店长'}},
                             {'id': 'store', 'type': 'ENUMERATION', 'value': {}}]} for identifier in ('u', 'v')}
        self.fail = False

    def pages(self, resource, **params):
        if self.fail:
            raise RuntimeError('FEISHU_UNAVAILABLE')
        if resource == 'scopes':
            yield {'department_ids': ['d'], 'user_ids': [], 'group_ids': ['group'], 'has_more': False}
        elif resource == 'children':
            yield {'items': [{'open_department_id': 'd'}] if params['department_id'] == '0' else [], 'has_more': False}
        elif resource == 'users':
            # 两页人员都通过部门遍历发现，不需要管理员提交名单。
            yield {'items': [{'user_id': 'u'}] if params['department_id'] == 'd' else [], 'has_more': params['department_id'] == 'd'}
            if params['department_id'] == 'd':
                yield {'items': [{'user_id': 'v'}], 'has_more': False}
        elif resource == 'custom_attrs':
            yield {'items': [{'id': key, 'type': 'ENUMERATION', 'options': {'options': [{'id': 'manager', 'value': '店长'}]}} for key in ('role', 'store')], 'has_more': False}

    def detail(self, kind, identifier):
        return deepcopy((self.users if kind == 'user' else self.departments)[identifier])


@pytest.fixture
def setup(sqlite_sessions):
    settings = Settings(session_secret='s' * 32, feishu_app_id='app', feishu_app_secret='test-secret',
                        feishu_tenant_key='tenant', feishu_redirect_uri='https://test.invalid/admin/auth/callback')
    with sqlite_sessions.begin() as db:
        state = db.get(DatasetState, 1)
        state.initialization_status, state.dataset_epoch = 'pending', 'pending'
        db.add(WorkerLease(id=1, generation=0))
        db.add(FeishuConnection(id=1, app_id='app', tenant_key='tenant', status='connected', custom_attrs=MAPPINGS))
    api = Feishu()
    service = InitializationService(sqlite_sessions, settings, api)
    return sqlite_sessions, service, api, settings


def ready(service):
    assert service.run_check(1, 'admin:ou')['checks'][-1]['status'] == 'passed'
    assert service.run_check(2, 'admin:ou')['checks'][-1]['status'] == 'passed'
    assert service.run_check(3, 'admin:ou')['checks'][-1]['status'] == 'passed'
    assert service.run_check(4, 'admin:ou')['phase'] == 'ready'


def worker_for(setup):
    sessions, _, api, settings = setup
    worker = Worker(sessions, Collector(api), initialization_settings=settings)
    assert worker.acquire(utcnow())
    return worker


def test_preflight_and_ordinary_api_paths_cannot_bypass(setup):
    sessions, service, _, _ = setup
    with pytest.raises(InitializationFailure, match='PREFLIGHT_REQUIRED'):
        service.start('admin:ou')
    with pytest.raises(RuntimeError, match='INITIALIZATION_WIZARD_REQUIRED'):
        SqlSyncJobRepository(sessions).submit('initialize', None, 'admin:ou', utcnow())
    with pytest.raises(RuntimeError, match='INITIALIZATION_INCOMPLETE'):
        SqlSyncJobRepository(sessions).submit('full', None, 'agent', utcnow())
    with pytest.raises(InitializationFailure, match='INITIALIZATION_WIZARD_REQUIRED'):
        Publisher(sessions).publish(Candidate(full=True, coverage_status='complete'))
    service.run_check(1, 'admin:ou')
    service.run_check(2, 'admin:ou')
    assert service.run_check(3, 'admin:ou')['phase'] == 'pending'
    with pytest.raises(InitializationFailure, match='PREFLIGHT_REQUIRED'):
        service.start('admin:ou')


def test_real_pipeline_without_evidence_reads_all_pages_and_accepts_official_enum_shape(setup):
    sessions, service, _, _ = setup
    ready(service)
    job_id = service.start('admin:ou')
    assert service.start('admin:another') == job_id
    with pytest.raises(InitializationFailure):
        service.configure(MAPPINGS, 'admin:another')
    worker = worker_for(setup)
    assert worker.step()
    status = service.status()
    assert status['complete'] and status['phase'] == 'complete'
    assert status['counts'] == {'departments': 1, 'employees': 2}
    assert status['job']['progress']['employees_processed'] == 2
    with sessions() as db:
        assert db.get(DatasetState, 1).coverage_status == 'complete'
        assert db.get(Employee, 'v').primary_department_id == 'd'
        assert db.get(Employee, 'u').permission_role_name == '店长'
        assert db.get(SyncJob, job_id).status == 'succeeded'


@pytest.mark.parametrize('leader', ['missing', None, '', 'v'])
def test_optional_employee_leader_passes_preflight_and_full_pipeline(setup, leader):
    sessions, service, api, _ = setup
    del api.users['v']['leader_user_id']
    if leader == 'missing':
        del api.users['u']['leader_user_id']
    else:
        api.users['u']['leader_user_id'] = leader
    ready(service)
    service.start('admin:ou')
    assert worker_for(setup).step()
    assert service.status()['complete']
    with sessions() as db:
        assert db.get(Employee, 'v').leader_user_id is None
        assert db.get(Employee, 'u').leader_user_id == (None if leader == 'missing' else leader)


@pytest.mark.parametrize('leader', [123, [], 'x' * 192])
def test_optional_employee_leader_still_rejects_invalid_values(setup, leader):
    _, service, api, _ = setup
    api.users['u']['leader_user_id'] = leader
    for step in (1, 2, 3):
        service.run_check(step, 'admin:ou')
    status = service.run_check(4, 'admin:ou')
    assert status['phase'] == 'precheck_failed'
    assert status['last_error']['issues'][0]['field'] == 'leader_user_id'


@pytest.mark.parametrize('leader', ['unknown', 'u'])
def test_optional_employee_leader_still_rejects_dangling_or_cyclic_relation(setup, leader):
    _, service, api, _ = setup
    api.users['u']['leader_user_id'] = leader
    ready(service)
    service.start('admin:ou')
    assert worker_for(setup).step()
    assert service.status()['phase'] == 'failed'


@pytest.mark.parametrize('problem', ['missing_field', 'missing_primary', 'read_failure', 'coverage_changed'])
def test_full_stage_failure_keeps_pending_and_never_automatically_retries(setup, problem):
    sessions, service, api, _ = setup
    ready(service)
    job_id = service.start('admin:ou')
    if problem == 'missing_field':
        del api.users['v']['job_title']
    elif problem == 'missing_primary':
        api.users['v']['orders'] = []
    elif problem == 'read_failure':
        api.fail = True
    else:
        with sessions.begin() as db:
            db.add(SystemSetting(key='coverage_invalidated', value='true'))
    worker = worker_for(setup)
    assert worker.step()
    with sessions() as db:
        assert db.get(SyncJob, job_id).status == 'failed'
        assert db.get(SyncJob, job_id).retry_count == 0
        assert db.get(DatasetState, 1).initialization_status == 'pending'
        assert list(db.scalars(select(Employee))) == []
    assert service.status()['phase'] == 'failed'
    with pytest.raises(ValueError):
        SqlSyncJobRepository(sessions).retry(job_id, 'admin:ou', utcnow())


def test_interruption_cannot_resume_and_cleanup_preserves_auth_config_and_failure_audit(setup):
    sessions, service, _, _ = setup
    ready(service)
    job_id = service.start('admin:ou')
    with sessions.begin() as db:
        job = db.get(SyncJob, job_id)
        job.status, job.lease_expires_at = 'running', utcnow() - timedelta(seconds=1)
        db.add(AdminAllowlist(open_id='ou', created_at=utcnow()))
        db.add(Department(id='old', feishu_department_id='old', name='旧门店'))
        db.flush()
        db.add(Department(id='child', feishu_department_id='child', parent_id='old', name='旧子部门'))
        db.add(Employee(id='old-user', feishu_user_id='old-user', name='旧人员', primary_department_id='old'))
        db.flush()
        db.add(EmployeeDepartment(employee_id='old-user', department_id='old'))
        db.add(EmployeeStore(employee_id='old-user', store_id='old', path=['old']))
        db.add(StoreProfile(department_id='old', is_store=True, store_code='OLD', notes='旧备注'))
        db.add(StoreCodeReservation(department_id='old', store_code='OLD', reserved_at=utcnow()))
        db.add(EventInbox(event_id='old-event', event_type='contact.user.updated_v3', object_id='old-user', payload={}, status='queued', received_at=utcnow()))
    assert service.status()['phase'] == 'failed'
    status = service.restart('admin:ou')
    assert status['phase'] == 'pending' and status['checks'] == [] and status['evidence'] is None
    with sessions() as db:
        for model in (EmployeeStore, EmployeeDepartment, StoreProfile, StoreCodeReservation, Employee, Department):
            assert list(db.scalars(select(model))) == []
        assert db.get(AdminAllowlist, 'ou') is not None
        assert db.get(FeishuConnection, 1).custom_attrs == MAPPINGS
        assert db.get(SyncJob, job_id).error_code == 'INITIALIZATION_INTERRUPTED'
        assert db.get(EventInbox, 'old-event').status == 'superseded'
        assert any(row.after_data.get('action') == 'cleanup' for row in db.scalars(select(ChangeLog)))
    with pytest.raises(InitializationFailure, match='PREFLIGHT_REQUIRED'):
        service.start('admin:ou')
    with pytest.raises(ValueError, match='STALE_LEASE'):
        Publisher(sessions).publish(Candidate(full=True), job_id, 0)


def test_changed_settings_invalidate_all_checks_and_coverage(setup):
    _, service, _, _ = setup
    ready(service)
    status = service.configure(MAPPINGS, 'admin:ou')
    assert status['checks'] == [] and status['evidence'] is None
    with pytest.raises(InitializationFailure):
        service.start('admin:ou')


def test_interrupted_precheck_has_a_visible_retry_and_cannot_release_start(setup):
    sessions, service, _, _ = setup
    service.run_check(1, 'admin:ou')
    with sessions.begin() as db:
        flow = load_flow(db)
        flow.update(phase='checking', checking_step=2, operation='abandoned',
                    operation_expires_at=(utcnow() - timedelta(seconds=1)).isoformat())
        save_flow(db, flow)
    status = service.status()
    assert status['phase'] == 'precheck_failed'
    assert status['checks'][-1]['step'] == 2 and status['checks'][-1]['status'] == 'failed'
    assert service.run_check(2, 'admin:ou')['checks'][-1]['status'] == 'passed'
    with pytest.raises(InitializationFailure, match='PREFLIGHT_REQUIRED'):
        service.start('admin:ou')


def test_null_orphan_lease_fails_with_audit_and_is_not_requeued(setup):
    sessions, service, _, _ = setup
    ready(service)
    job_id = service.start('admin:ou')
    with sessions.begin() as db:
        db.get(SyncJob, job_id).status = 'running'
    worker = worker_for(setup)
    worker.recover(utcnow())
    assert not worker.step()
    assert service.status()['phase'] == 'failed'
    with sessions() as db:
        job = db.get(SyncJob, job_id)
        assert job.status == 'failed' and job.retry_count == 0
        assert any(log.after_data.get('error_code') == 'INITIALIZATION_INTERRUPTED'
                   for log in db.scalars(select(ChangeLog)))


def test_publication_failure_rolls_back_business_and_completion_together(setup):
    sessions, service, _, _ = setup
    ready(service)
    job_id = service.start('admin:ou')
    def fail_completion(_mapper, _connection, row):
        if row.object_type == 'initialization' and row.after_data.get('status') == 'complete':
            raise RuntimeError('INJECTED_COMPLETION_AUDIT_FAILURE')
    event.listen(ChangeLog, 'before_insert', fail_completion)
    try:
        assert worker_for(setup).step()
    finally:
        event.remove(ChangeLog, 'before_insert', fail_completion)
    assert service.status()['phase'] == 'failed'
    with sessions() as db:
        assert db.get(DatasetState, 1).initialization_status == 'pending'
        assert list(db.scalars(select(Employee))) == []
        assert list(db.scalars(select(Department))) == []
        assert db.get(SyncJob, job_id).status == 'failed'


def test_remote_definition_change_during_collection_fails_entire_attempt(setup):
    _, service, api, _ = setup
    ready(service)
    service.start('admin:ou')
    detail = api.detail
    def change_definition(kind, identifier):
        value = detail(kind, identifier)
        if kind == 'user':
            original = api.pages
            def changed(resource, **params):
                for page in original(resource, **params):
                    if resource == 'custom_attrs':
                        page['items'][0]['options']['options'][0]['value'] = '修改后的选项'
                    yield page
            api.pages = changed
        return value
    api.detail = change_definition
    worker_for(setup).step()
    assert service.status()['last_error']['code'] == 'PREFLIGHT_STALE'


def test_ready_flow_rechecks_scope_and_environment_changes(setup):
    sessions, service, _, settings = setup
    ready(service)
    with sessions.begin() as db:
        db.add(SystemSetting(key='coverage_invalidated', value='true'))
    status = service.status()
    assert status['phase'] == 'pending' and len(status['checks']) == 1 and status['evidence'] is None
    ready(service)
    settings.feishu_app_secret = type(settings.feishu_app_secret)('changed-secret')
    status = service.status()
    assert status['phase'] == 'pending' and status['checks'] == [] and status['evidence'] is None


def test_http_auth_gate_keeps_only_initialization_available_and_enforces_csrf(setup):
    sessions, service, _, settings = setup
    identities = SqlIdentityRepository(sessions, settings.session_secret.get_secret_value())
    identities.add_admin('ou', 'test', utcnow())
    issued = identities.create_session('ou', 'csrf', utcnow() + timedelta(hours=1), utcnow())
    runtime = SimpleNamespace(sessions=sessions, identities=identities, jobs=SqlSyncJobRepository(sessions))
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_initialization_service] = lambda: service
    try:
        client = TestClient(app)
        assert client.get('/admin/api/initialization').status_code == 401
        client.cookies.set('org_session', issued.token)
        client.cookies.set('org_csrf', 'csrf')
        assert client.get('/admin/auth/session').json()['data']['initialization_complete'] is False
        for path in ('/admin/api/settings/custom-attrs', '/admin/api/sync/jobs', '/admin/api/admin-allowlist', '/admin/api/change-logs', '/admin/api/system/version'):
            response = client.get(path)
            assert response.status_code == 409, path
            assert response.json()['error']['code'] == 'INITIALIZATION_INCOMPLETE'
        assert client.get('/admin/api/initialization').status_code == 200
        assert client.post('/admin/api/initialization/checks/1').status_code == 403
        assert client.post('/admin/api/initialization/checks/1', headers={'X-CSRF-Token': 'csrf'}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_old_evidence_failure_can_retry_without_cleanup_or_manual_roster(setup):
    sessions, service, _, _ = setup
    service.run_check(1, 'admin:ou')
    service.run_check(2, 'admin:ou')
    with sessions.begin() as db:
        flow = load_flow(db)
        flow['phase'] = 'precheck_failed'
        flow['checks'].append({'step': 3, 'title': '试读部门与人员', 'status': 'failed',
                              'items': [{'key': 'departmentless', 'status': 'failed'}]})
        flow['evidence'] = {'employee_ids': ['obsolete'], 'departmentless_ids': ['obsolete']}
        save_flow(db, flow)
    status = service.run_check(3, 'admin:ou')
    assert status['checks'][-1]['status'] == 'passed'
    assert all(item['key'] != 'departmentless' for item in status['checks'][-1]['items'])
    assert service.run_check(4, 'admin:ou')['phase'] == 'ready'
    service.start('admin:ou')
    assert worker_for(setup).step()
    assert service.status()['complete']


@pytest.mark.parametrize('text', ['直营门店', '', None, '店' * 255])
def test_text_store_attribute_initialization_and_regular_sync(setup, text):
    from app.sync.collector import normalize_user
    sessions, service, api, _ = setup
    original_pages = api.pages

    def pages(resource, **params):
        for page in original_pages(resource, **params):
            if resource == 'custom_attrs':
                page['items'][1] = {'id': 'store', 'type': 'TEXT'}
            yield page

    api.pages = pages
    for raw in api.users.values():
        raw['custom_attrs'][1] = {'id': 'store', 'type': 'TEXT', 'value': {'text': text}}
    ready(service)
    service.start('admin:ou')
    assert worker_for(setup).step()
    assert service.status()['complete']
    with sessions() as db:
        employee = db.get(Employee, 'u')
        assert employee.store_attribute_id is None
        assert employee.store_attribute_name == text
    normalized = normalize_user(api.users['u'], MAPPINGS)
    assert normalized['store_attribute_id'] is None
    assert normalized['store_attribute_name'] == text


@pytest.mark.parametrize('attr', [
    None,
    {'id': 'store', 'type': 'TEXT', 'value': {}},
    {'id': 'store', 'type': 'TEXT', 'value': {'text': 42}},
    {'id': 'store', 'type': 'TEXT', 'value': {'text': '店' * 256}},
    {'id': 'store', 'type': 'ENUMERATION', 'value': {}},
])
def test_text_store_attribute_rejects_unreadable_and_invalid_values(attr):
    from app.initialization.validation import validate_user, validate_definitions
    api = Feishu()
    definitions = next(api.pages('custom_attrs'))['items']
    definitions[1] = {'id': 'store', 'type': 'TEXT'}
    definitions = validate_definitions(definitions, MAPPINGS)
    raw = api.users['u']
    raw['custom_attrs'] = raw['custom_attrs'][:1] + ([attr] if attr else [])
    with pytest.raises(InitializationFailure):
        validate_user(raw, MAPPINGS, definitions)


@pytest.mark.parametrize('value', [{}, {'text': 42}, {'text': '店' * 256}])
def test_regular_sync_marks_invalid_text_store_attribute_pending(value):
    api = Feishu()
    api.users['u']['custom_attrs'][1] = {'id': 'store', 'type': 'TEXT', 'value': value}
    candidate = Candidate()
    Collector(api, custom_mappings=MAPPINGS)._user(candidate, 'u')
    assert candidate.pending == [('employee', 'u')]
    assert not candidate.employees
