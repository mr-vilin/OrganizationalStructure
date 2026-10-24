"""仅在明确提供独立 MySQL _test URL 时执行；不使用 SQLite 替代。"""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.evaluation.cases import load_case
from app.evaluation.fixtures import evaluation_database, reset_test_database, seed_case, verify_test_database, FAKE_APP_ID, FAKE_TENANT_KEY
from app.persistence import models as m
from app.persistence.database import create_mysql_engine


CASES = Path(__file__).parents[1] / 'evaluation' / 'cases'


def assert_reset_baseline(factory):
    with factory() as db:
        assert db.get(m.DatasetState, 1).dataset_epoch == 'pending'
        assert db.get(m.DatasetState, 1).data_version == 0
        assert db.get(m.DatasetState, 1).initialization_status == 'pending'
        assert db.get(m.WorkerLease, 1).owner is None
        assert db.get(m.WorkerLease, 1).generation == 0
        assert db.get(m.SystemSetting, 'task_queue_lock').value == '1'
        assert json.loads(db.get(m.SystemSetting, 'reconcile_schedule').value)['enabled'] is False
        connection = db.get(m.FeishuConnection, 1)
        assert (connection.app_id, connection.tenant_key) == (FAKE_APP_ID, FAKE_TENANT_KEY)
        counts = {table.name: db.scalar(select(func.count()).select_from(table)) for table in m.Base.metadata.tables.values()}
        assert {key: value for key, value in counts.items() if value} == {
            'dataset_state': 1, 'system_setting': 2, 'worker_lease': 1, 'feishu_connection': 1}
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0009_operation_receipt'


@pytest.mark.parametrize('case_id', ['ORG_AGENT_READ_PRIMARY_STORE', 'ORG_AGENT_READ_NOT_IN_STORE'])
def test_literal_fixture_seed_read_cleanup_repeat(evaluation_mysql_database, case_id):
    factory = evaluation_mysql_database
    case = load_case(CASES / (case_id + '.yaml'))
    original = deepcopy(case.fixture)
    for _ in range(2):
        seed_case(factory, case)
        with factory() as db:
            actual = verify_test_database(db.connection())
            assert actual['mysql_version'].startswith('8.4.')
            for section, model in [('departments', m.Department), ('employees', m.Employee),
                                   ('employee_departments', m.EmployeeDepartment), ('store_profiles', m.StoreProfile),
                                   ('employee_stores', m.EmployeeStore), ('system_settings', m.SystemSetting)]:
                for literal in case.fixture[section]:
                    identity = tuple(literal[column.key] for column in model.__mapper__.primary_key)
                    actual_row = db.get(model, identity)
                    assert actual_row is not None
                    assert {key: getattr(actual_row, key) for key in literal} == literal
            employee = db.get(m.Employee, case.expected_state['employee_id'])
            assert employee.primary_department_id == case.expected_state['primary_department_id']
            assert employee.primary_store_status == case.expected_state['primary_store_status']
            stores = db.scalars(select(m.EmployeeStore).where(m.EmployeeStore.employee_id == employee.id)).all()
            assert {row.store_id for row in stores} == set(case.expected_state['store_ids'])
            assert next((row.store_id for row in stores if row.is_primary), None) == case.expected_state['primary_store_id']
            assert [{'employee_id': row.employee_id, 'store_id': row.store_id, 'is_primary': row.is_primary, 'path': row.path}
                    for row in sorted(stores, key=lambda row: row.store_id)] == sorted(case.fixture['employee_stores'], key=lambda row: row['store_id'])
            assert db.get(m.DatasetState, 1).dataset_epoch == case.fixture['dataset_state']['dataset_epoch']
            assert db.get(m.DatasetState, 1).data_version == 1
            relations = db.scalars(select(m.EmployeeDepartment)).all()
            assert len(relations) == 2 and sum(row.is_primary for row in relations) == 1
        assert case.fixture == original
        reset_test_database(str(factory.kw['bind'].url.render_as_string(hide_password=False)))
        assert_reset_baseline(factory)


def test_seed_failure_rolls_back_all_facts_and_keeps_schedule_disabled(evaluation_mysql_database):
    factory = evaluation_mysql_database
    case = load_case(CASES / 'ORG_AGENT_READ_PRIMARY_STORE.yaml')
    case.fixture['departments'][1]['parent_id'] = 'missing-parent'
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        seed_case(factory, case)
    assert_reset_baseline(factory)


def test_reset_refuses_owned_lease_without_deleting_facts(evaluation_mysql_database):
    factory = evaluation_mysql_database
    seed_case(factory, load_case(CASES / 'ORG_AGENT_READ_PRIMARY_STORE.yaml'))
    url = factory.kw['bind'].url.render_as_string(hide_password=False)
    try:
        with factory.begin() as db:
            db.get(m.WorkerLease, 1).owner = 'test-synthetic-worker'
        with pytest.raises(RuntimeError, match='EVALUATION_WORKER_NOT_QUIET'):
            reset_test_database(url)
        with factory() as db:
            assert db.get(m.Employee, 'eval_employee_primary') is not None
    finally:
        with factory.begin() as db:
            db.get(m.WorkerLease, 1).owner = None


def test_preflight_checks_actual_session_not_only_configuration(evaluation_mysql_database):
    with evaluation_mysql_database() as db:
        db.execute(text('SET NAMES latin1'))
        try:
            with pytest.raises(ValueError, match='EVALUATION_MYSQL_CHARSET_MISMATCH'):
                verify_test_database(db.connection())
        finally:
            db.execute(text('SET NAMES utf8mb4 COLLATE utf8mb4_general_ci'))


def test_context_cleans_seeded_facts_on_exception_and_rejects_parallel_owner():
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；Evaluation 真实 MySQL 验收尚未执行')
    case = load_case(CASES / 'ORG_AGENT_READ_NOT_IN_STORE.yaml')
    with pytest.raises(RuntimeError, match='synthetic-case-failure'):
        with evaluation_database(url) as factory:
            seed_case(factory, case)
            with pytest.raises(RuntimeError, match='EVALUATION_DATABASE_BUSY'):
                with evaluation_database(url):
                    pytest.fail('并发生命周期不应进入')
            raise RuntimeError('synthetic-case-failure')
    engine = create_mysql_engine(url)
    try:
        from app.persistence.database import session_factory
        assert_reset_baseline(session_factory(engine))
    finally:
        engine.dispose()


def test_reset_clears_all_runtime_audit_identity_and_self_referencing_rows(evaluation_mysql_database):
    from datetime import datetime

    factory = evaluation_mysql_database
    seed_case(factory, load_case(CASES / 'ORG_AGENT_READ_PRIMARY_STORE.yaml'))
    now = datetime(2026, 10, 15)
    with factory.begin() as db:
        db.add(m.SyncJob(id='test-job', type='reconcile', requested_by='eval', status='failed', created_at=now, updated_at=now))
        db.flush()
        db.add_all([
            m.SyncJobDetail(job_id='test-job', object_type='employee', object_id='eval_employee_primary', status='failed'),
            m.SyncStaging(job_id='test-job', object_type='employee', source_id='eval_employee_primary', normalized_data={}),
            m.ChangeLog(object_type='employee', object_id='eval_employee_primary', source='eval', job_id='test-job', committed_at=now),
            m.EventInbox(event_id='test-event', event_type='contact.user.updated_v3', object_id='eval_employee_primary', payload={}, status='failed', received_at=now),
            m.PendingFact(object_type='employee', source_id='eval_employee_primary', normalized_data={}, error_code='FEISHU_UNAVAILABLE', updated_at=now),
            m.StoreCodeReservation(store_code='EVAL_RESERVED', department_id='store_people', reserved_at=now),
            m.OperationReceipt(operation_id='test-operation', idempotency_key='test-key', capability='reconcile', actor_type='ci', actor_id='eval', environment='test', run_id='test-run', case_id='ORG_AGENT_READ_PRIMARY_STORE', request_hash='0' * 64, status='failed', before_epoch='test-baseline', before_version=1, created_at=now, updated_at=now),
            m.OAuthState(digest='0' * 64, expires_at=now),
            m.LoginIdentity(open_id='test-open', user_id='test-user', tenant_key='eval-fake-tenant'),
            m.AdminAllowlist(open_id='test-open', created_at=now),
            m.AdminSession(id='test-session', token_digest='f' * 64, open_id='test-open', csrf_hash='0' * 64, expires_at=now),
            m.ApiClient(id='test-client', name='合成客户端', secret_hash='0' * 64, created_at=now),
        ])
        db.get(m.WorkerLease, 1).generation = 99
    with factory() as db:
        assert all(db.scalar(select(func.count()).select_from(table)) > 0 for table in m.Base.metadata.tables.values())
    reset_test_database(factory.kw['bind'].url.render_as_string(hide_password=False))
    assert_reset_baseline(factory)


@pytest.mark.parametrize('change,error', [('enabled', 'EVALUATION_SCHEDULE_MUST_BE_DISABLED'), ('duplicate', 'EVALUATION_FIXTURE_SETTINGS_DUPLICATE')])
def test_seed_rejects_unsafe_schedule_before_writing(evaluation_mysql_database, change, error):
    factory = evaluation_mysql_database
    case = load_case(CASES / 'ORG_AGENT_READ_PRIMARY_STORE.yaml')
    if change == 'enabled':
        value = json.loads(case.fixture['system_settings'][0]['value'])
        value['enabled'] = True
        case.fixture['system_settings'][0]['value'] = json.dumps(value)
    else:
        case.fixture['system_settings'].append(deepcopy(case.fixture['system_settings'][0]))
    with pytest.raises(ValueError, match=error):
        seed_case(factory, case)
    assert_reset_baseline(factory)
