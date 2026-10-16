"""独立断言硬门槛；纯逻辑测试不连接数据库。"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation.assertions import (
    assert_case_postconditions, assert_forbidden_effects, assert_trace_policy,
)
from app.evaluation.evidence import (
    BUSINESS_TABLES, DatabaseSnapshot, EvaluationEvidence, capture_worker_output,
    independent_reader,
)
from app.evaluation.cases import load_case
from app.evaluation.fake_feishu import FakeFeishu
from app.evaluation.models import AgentRun, AgentRunContext, ToolTraceEvent

CASES = Path(__file__).parent / 'cases'


def case(name='PRIMARY_STORE'):
    return load_case(CASES / f'ORG_AGENT_READ_{name}.yaml')


def evidence(c=None):
    c = c or case()
    tables = {name: [] for name in BUSINESS_TABLES}
    for section, table in [('departments', 'department'), ('employees', 'employee'),
                           ('employee_departments', 'employee_department'),
                           ('employee_stores', 'employee_store'), ('store_profiles', 'store_profile')]:
        tables[table] = deepcopy(c.fixture[section])
    tables['dataset_state'] = [deepcopy(c.fixture['dataset_state'])]
    snap = DatabaseSnapshot(tables)
    obs = EvaluationEvidence(snap, DatabaseSnapshot(deepcopy(tables)),
        AgentRunContext('test-assertions', c.case_id, 'eval-actor', 'test'),
        fake_writes={'count': 0, 'by_method': {}}, output=capture_worker_output(AgentRun('', (), {})))
    return attach_read_proofs(obs, [event(arguments={'employee_id': c.expected_state['employee_id']})], [read_wire(c)])


def codes(failures):
    return {failure.code for failure in failures}


def event(tool='get_employee', code=None, sequence=1, arguments=None, operation_id=None):
    return ToolTraceEvent(sequence, tool, arguments or {}, code, operation_id,
        '2026-10-15T00:00:00Z', '2026-10-15T00:00:01Z')


@pytest.mark.parametrize('name', ['PRIMARY_STORE', 'NOT_IN_STORE'])
def test_literal_read_facts_and_all_six_forbidden(name):
    c = case(name)
    obs = evidence(c)
    assert assert_case_postconditions(c, obs) == []
    assert assert_forbidden_effects(c, obs) == []


@pytest.mark.parametrize('field,value', [('primary_department_id', None), ('primary_store_status', 'unknown')])
def test_bad_fact_cannot_be_masked_by_worker_success(field, value):
    obs = evidence()
    obs.after._tables['employee'][0][field] = value
    obs.output = capture_worker_output(AgentRun('完成', (), {'execution': 'verified', 'fact_quality': 'resolved'}))
    assert 'FACT_MISMATCH' in codes(assert_case_postconditions(case(), obs))


def test_wrong_projection_fails_without_production_algorithm():
    obs = evidence()
    obs.after._tables['employee_store'][0]['is_primary'] = True
    assert 'FACT_MISMATCH' in codes(assert_case_postconditions(case(), obs))


@pytest.mark.parametrize('expected', [{'typo': True}, {'store_ids': []}, {'rows': []}])
def test_unsupported_or_incomplete_expected_never_passes(expected):
    assert assert_case_postconditions(replace(case(), expected_state=expected), evidence())


def test_missing_evidence_and_unknown_forbidden_fail_closed():
    assert 'MISSING_EVIDENCE' in codes(assert_case_postconditions(case(), {}))
    c = replace(case(), forbidden_effects=({'predicate': 'made_up'},))
    assert 'UNSUPPORTED_PREDICATE' in codes(assert_forbidden_effects(c, evidence()))


def test_epoch_change_and_raw_business_mutation_fail():
    obs = evidence()
    obs.after._tables['dataset_state'][0]['dataset_epoch'] = 'test-other'
    obs.after._tables['employee'][0]['name'] = 'synthetic-private-name'
    result = assert_forbidden_effects(case(), obs)
    assert 'FORBIDDEN_EFFECT' in codes(result)
    assert 'synthetic-private-name' not in repr(result)


def test_fake_rejected_write_is_still_forbidden():
    obs = evidence()
    fake = FakeFeishu()
    with pytest.raises(Exception):
        fake._request('POST', '/irrelevant')
    obs.fake_writes = {'count': fake.write_attempt_count, 'by_method': fake.write_attempts_by_method}
    assert 'FORBIDDEN_EFFECT' in codes(assert_forbidden_effects(case(), obs))


def test_trace_readonly_and_dataset_changed_requires_actual_reread():
    assert 'TOOL_FORBIDDEN' in codes(assert_trace_policy(case(), (event('apply_store_changes'),)))
    assert 'DATASET_REREAD_REQUIRED' in codes(assert_trace_policy(case(), (event(code='DATASET_CHANGED'),)))


def test_secret_detected_before_redaction():
    raw = AgentRun('password=canary-secret', (event(arguments={'access_token': 'raw-canary-token'}),), {})
    captured = capture_worker_output(raw, sensitive_values=('canary-secret',))
    obs = evidence()
    obs.output = captured
    assert 'SENSITIVE_LEAK' in codes(assert_case_postconditions(case(), obs))
    assert 'canary' not in repr(captured.redacted_run)
    assert 'canary' not in repr(assert_case_postconditions(case(), obs))


def operation_evidence(*, job=False):
    obs = evidence()
    capability = 'request_sync' if job else 'apply_store_changes'
    receipt = {'operation_id': 'op-eval', 'capability': capability, 'actor_type': 'ci',
        'actor_id': obs.context.actor_id, 'environment': 'test', 'run_id': obs.context.run_id,
        'case_id': obs.context.case_id, 'status': 'submitted', 'job_id': 'job-eval' if job else None,
        'before_epoch': 'test-eval-primary-store', 'before_version': 1,
        'committed_epoch': 'test-eval-primary-store', 'committed_version': 2,
        'result_summary': {'audit_ids': [91]}, 'error_code': None}
    obs.after._tables['dataset_state'][0]['data_version'] = 2
    obs.after._tables['operation_receipt'] = [receipt]
    obs.after._tables['change_log'] = [{'id': 91, 'object_type': 'department' if job else 'store',
        'object_id': 'store_people', 'actor': 'sync' if job else obs.context.actor_id,
        'source': 'feishu' if job else 'admin', 'job_id': 'job-eval' if job else None}]
    if job:
        obs.after._tables['sync_job'] = [{'id': 'job-eval', 'type': 'subtree', 'root_department_id': 'store_people',
            'requested_by': obs.context.actor_id, 'status': 'succeeded', 'failure_count': 0}]
    obs.output = capture_worker_output(AgentRun('', (event(capability, operation_id='op-eval',
        arguments={'changes': [{'department_id': 'store_people', 'is_store': True}]}),), {}))
    c = replace(case(), allowed_tools=(*case().allowed_tools, capability), expected_state={
        'operation': {'capability': capability, 'status': 'submitted', 'count': 1,
                      'audit_required': True, 'job_required': job}, 'version_delta': 1,
        'execution': 'submitted', 'fact_quality': 'resolved'})
    return c, obs


@pytest.mark.parametrize('job', [False, True])
def test_real_fact_shape_receipt_audit_and_job_link(job):
    c, obs = operation_evidence(job=job)
    assert assert_case_postconditions(c, obs) == []


@pytest.mark.parametrize('mutation,code', [
    ('audit_deleted', 'AUDIT_MISSING'), ('audit_wrong_actor', 'AUDIT_MISSING'),
    ('receipt_deleted', 'RECEIPT_MISSING'), ('receipt_other_run', 'IDENTITY_MISMATCH'),
    ('receipt_future_version', 'VERSION_MISMATCH'), ('receipt_other_epoch', 'VERSION_MISMATCH'),
    ('audit_wrong_object', 'AUDIT_MISSING'),
])
def test_receipt_audit_mutations_cannot_pass(mutation, code):
    c, obs = operation_evidence()
    if mutation == 'audit_deleted': obs.after._tables['change_log'] = []
    if mutation == 'audit_wrong_actor': obs.after._tables['change_log'][0]['actor'] = 'other'
    if mutation == 'audit_wrong_object': obs.after._tables['change_log'][0]['object_id'] = 'other'
    if mutation == 'receipt_deleted': obs.after._tables['operation_receipt'] = []
    if mutation == 'receipt_other_run': obs.after._tables['operation_receipt'][0]['run_id'] = 'test-other'
    if mutation == 'receipt_future_version': obs.after._tables['operation_receipt'][0]['committed_version'] = 99
    if mutation == 'receipt_other_epoch': obs.after._tables['operation_receipt'][0]['committed_epoch'] = 'test-other'
    assert code in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('field,value', [('status', 'future_unknown'), ('status', 'running'), ('failure_count', 1)])
def test_job_unknown_running_partial_cannot_claim_verified(field, value):
    c, obs = operation_evidence(job=True)
    obs.after._tables['sync_job'][0][field] = value
    obs.output = capture_worker_output(replace(obs.output._run, terminal_observation={'execution': 'verified', 'fact_quality': 'resolved'}))
    assert 'TERMINAL_MISMATCH' in codes(assert_case_postconditions(c, obs))


def test_subtree_literal_rows_partial_and_no_fake_truth():
    c, obs = operation_evidence(job=True)
    obs.after._tables['sync_job'][0]['failure_count'] = 1
    c = replace(c, expected_state={**c.expected_state, 'execution': 'partial', 'fact_quality': 'partial',
        'rows': [{'table': 'sync_job', 'where': {'root_department_id': 'store_people'},
                  'equals': {'status': 'succeeded', 'failure_count': 1}, 'count': 1}]})
    assert assert_case_postconditions(c, obs) == []
    obs.after._tables['sync_job'][0]['root_department_id'] = 'other'
    assert 'FACT_MISMATCH' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('bad', [
    {'table': 'employee', 'where': {}, 'equals': {}, 'count': 0},
    {'table': 'employee', 'where': {'id': 'a'}, 'equals': {}, 'count': True},
    {'table': 'employee', 'where': {'name': 'secret'}, 'equals': {}, 'count': 0},
    {'table': 'sql', 'where': {'id': 'a'}, 'equals': {}, 'count': 0},
    {'table': 'employee', 'where': {'id': 'a'}, 'equals': {}, 'count': 0, 'ignore': True},
])
def test_row_predicate_malformed_or_unknown_never_passes(bad):
    c = replace(case(), expected_state={'rows': [bad]})
    assert assert_case_postconditions(c, evidence())


def test_pending_protection_preserves_facts_memberships_allows_projection_reassessment():
    obs = evidence()
    rule = {'predicate': 'pending_protected', 'employee_ids': ['eval_employee_primary'], 'department_ids': ['people_service']}
    c = replace(case(), forbidden_effects=(rule,))
    obs.after._tables['employee'][0]['sync_quality'] = 'pending_verification'
    obs.after._tables['employee'][0]['primary_store_status'] = 'unknown'
    next(r for r in obs.after._tables['department'] if r['id'] == 'people_service')['sync_quality'] = 'pending_verification'
    obs.after._tables['employee_store'] = []
    assert assert_forbidden_effects(c, obs) == []
    obs.after._tables['employee_department'][0]['active'] = False
    assert 'FORBIDDEN_EFFECT' in codes(assert_forbidden_effects(c, obs))


@pytest.mark.parametrize('table', BUSINESS_TABLES)
def test_business_unchanged_covers_every_declared_table(table):
    obs = evidence()
    obs.after._tables[table].append({'synthetic_mutation': 'private-canary'})
    c = replace(case(), forbidden_effects=({'predicate': 'business_tables_unchanged'},))
    assert 'FORBIDDEN_EFFECT' in codes(assert_forbidden_effects(c, obs))


@pytest.mark.parametrize('predicate,table', [
    ('no_new_operation_receipts', 'operation_receipt'), ('no_new_sync_jobs', 'sync_job'), ('no_new_change_logs', 'change_log'),
])
def test_no_new_predicates_inspect_independent_primary_keys(predicate, table):
    obs = evidence()
    obs.after._tables[table] = [{'operation_id' if table == 'operation_receipt' else 'id': 'new'}]
    assert 'FORBIDDEN_EFFECT' in codes(assert_forbidden_effects(
        replace(case(), forbidden_effects=({'predicate': predicate},)), obs))


@pytest.mark.parametrize('missing', ['after_table', 'before_table', 'fake', 'output', 'column'])
def test_evidence_gaps_hard_fail(missing):
    obs = evidence()
    if missing == 'after_table': del obs.after._tables['employee_store']
    if missing == 'before_table': del obs.before._tables['employee']
    if missing == 'fake': obs.fake_writes = None
    if missing == 'output': obs.output = None
    if missing == 'column': del obs.after._tables['employee'][0]['primary_department_id']
    assert 'MISSING_EVIDENCE' in codes(assert_case_postconditions(case(), obs) + assert_forbidden_effects(case(), obs))


@pytest.mark.parametrize('value', [True, -1, '1'])
def test_invalid_version_delta(value):
    assert assert_case_postconditions(replace(case(), expected_state={'version_delta': value}), evidence())


def test_store_set_rejects_duplicate_expected_and_actual():
    c = case()
    c = replace(c, expected_state={**c.expected_state, 'store_ids': ['store_people', 'store_river', 'store_river']})
    assert 'FACT_MISMATCH' in codes(assert_case_postconditions(c, evidence()))
    obs = evidence()
    obs.after._tables['employee_store'].append(deepcopy(obs.after._tables['employee_store'][0]))
    assert 'FACT_MISMATCH' in codes(assert_case_postconditions(case(), obs))


def test_trace_conflict_recovery_requires_successful_fresh_read():
    first = event(code='DATASET_CHANGED')
    fresh = replace(event(sequence=2), started_at='2026-10-15T00:00:02Z', finished_at='2026-10-15T00:00:03Z')
    assert assert_trace_policy(case(), (first, fresh)) == []
    assert 'DATASET_REREAD_REQUIRED' in codes(assert_trace_policy(case(), (first, replace(fresh, arguments={'cursor': 'old'}))))
    assert 'DATASET_REREAD_REQUIRED' in codes(assert_trace_policy(case(), (first, replace(fresh, result_code='NOT_FOUND'))))


@pytest.mark.parametrize('bad', [
    replace(event(), sequence=0), replace(event(), finished_at='garbage'),
    replace(event(), started_at='2026-10-15T00:00:00'),
    replace(event(), finished_at='2026-10-15T00:00:31Z'),
])
def test_invalid_trace_fails(bad):
    assert assert_trace_policy(case(), (bad,))


@pytest.mark.parametrize('raw', ['Bearer synthetic-token', 'mysql+pymysql://u:p@local/test',
                                'SELECT name FROM employee', 'private@example.com', '13800001234'])
def test_outbound_sensitive_patterns_are_detected_and_never_echoed(raw):
    obs = evidence()
    obs.output = capture_worker_output(AgentRun(raw, (), {}))
    failures = assert_case_postconditions(case(), obs)
    assert 'SENSITIVE_LEAK' in codes(failures)
    assert raw not in repr(obs.output.redacted_run)
    assert raw not in repr([f.evidence for f in failures])


def test_private_db_raw_is_not_mistaken_for_leak_and_summary_is_allowlisted():
    obs = evidence()
    obs.after._tables['system_setting'] = [{'key': 'secret_key', 'value': 'private-secret'}]
    assert 'SENSITIVE_LEAK' not in codes(assert_case_postconditions(case(), obs))
    assert 'private-secret' not in repr(obs.summary())
    assert 'private-secret' not in repr(obs)


@pytest.mark.parametrize('name', ['PRIMARY_STORE', 'NOT_IN_STORE'])
def test_real_mysql_independent_readonly_consistent_snapshot_and_cleanup(name):
    import os
    from sqlalchemy import text, update, select, func
    from sqlalchemy.exc import DBAPIError
    from app.evaluation.fixtures import evaluation_database, seed_case, verify_test_database
    from app.persistence.database import create_mysql_engine
    from app.persistence.models import DatasetState, Base

    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；独立只读 MySQL 验收未执行')
    c = case(name)
    with evaluation_database(url) as factory:
        seed_case(factory, c)
        with independent_reader(url) as reader:
            before = reader.snapshot()
            info = verify_test_database(reader._connection)
            assert info['mysql_version'].startswith('8.4.')
            assert reader._connection.scalar(text('SELECT @@transaction_read_only')) == 1
            reader_id = reader._connection.scalar(text('SELECT CONNECTION_ID()'))
            with pytest.raises(DBAPIError) as denied:
                reader._connection.execute(update(DatasetState).where(DatasetState.id == 1).values(data_version=999))
            assert denied.value.orig.args[0] == 1792
            with factory.begin() as writer:
                assert writer.scalar(text('SELECT CONNECTION_ID()')) != reader_id
                writer.execute(update(DatasetState).where(DatasetState.id == 1).values(data_version=2))
            assert reader.snapshot().rows('dataset_state')[0]['data_version'] == 1
            with independent_reader(url) as latest:
                after = latest.snapshot()
                assert after.rows('dataset_state')[0]['data_version'] == 2
            obs = EvaluationEvidence(before, after, evidence(c).context,
                {'count': 0, 'by_method': {}}, capture_worker_output(AgentRun('', (), {})))
            wire = read_wire(c)
            wire['data']['meta']['data_version'] = wire['observation']['data_version'] = 2
            attach_read_proofs(obs, [event(arguments={'employee_id': c.expected_state['employee_id']})], [wire])
            assert assert_case_postconditions(c, obs) == []
            assert 'FORBIDDEN_EFFECT' in codes(assert_forbidden_effects(c, obs))
    engine = create_mysql_engine(url)
    try:
        with engine.connect() as connection:
            verify_test_database(connection)
            counts = {t.name: connection.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}
            assert {k:v for k,v in counts.items() if v} == {
                'dataset_state': 1, 'worker_lease': 1, 'system_setting': 2, 'feishu_connection': 1}
            assert connection.scalar(select(DatasetState.data_version)) == 0
    finally:
        engine.dispose()


def test_noop_submission_does_not_require_fabricated_audit():
    c, obs = operation_evidence()
    obs.after._tables['change_log'] = []
    receipt = obs.after._tables['operation_receipt'][0]
    receipt['result_summary'] = {'audit_ids': []}
    receipt['committed_version'] = 1
    obs.after._tables['dataset_state'][0]['data_version'] = 1
    c = replace(c, expected_state={**c.expected_state, 'version_delta': 0,
        'operation': {**c.expected_state['operation'], 'audit_required': False}})
    assert assert_case_postconditions(c, obs) == []


def test_actual_store_change_requires_audit_even_if_explicit_flag_false():
    c, obs = operation_evidence()
    before = obs.before._tables['store_profile'][0]
    after = obs.after._tables['store_profile'][0]
    after['is_store'] = False
    c = replace(c, expected_state={**c.expected_state,
        'operation': {**c.expected_state['operation'], 'audit_required': False}})
    log = obs.after._tables['change_log'][0]
    log['before_data'] = {k: before[k] for k in ('is_store', 'store_code', 'notes')}
    log['after_data'] = {k: after[k] for k in ('is_store', 'store_code', 'notes')}
    assert assert_case_postconditions(c, obs) == []
    obs.after._tables['change_log'] = []
    assert 'AUDIT_MISSING' in codes(assert_case_postconditions(c, obs))


def test_unknown_receipt_cannot_be_overridden_by_succeeded_job():
    c, obs = operation_evidence(job=True)
    obs.after._tables['operation_receipt'][0]['status'] = 'future_unknown'
    obs.output = capture_worker_output(replace(obs.output._run, terminal_observation={'execution': 'verified'}))
    assert 'TERMINAL_MISMATCH' in codes(assert_case_postconditions(c, obs))


def test_unknown_primary_projection_cannot_claim_resolved_quality():
    obs = evidence()
    obs.after._tables['employee'][0]['primary_store_status'] = 'unknown'
    obs.output = capture_worker_output(AgentRun('', (), {'fact_quality': 'resolved'}))
    c = replace(case(), expected_state={'data_version': 1})
    assert 'TERMINAL_MISMATCH' in codes(assert_case_postconditions(c, obs))


def test_successful_mutation_without_receipt_id_is_hard_failure():
    obs = evidence()
    obs.output = capture_worker_output(AgentRun('', (event('apply_store_changes'),), {}))
    assert 'RECEIPT_MISSING' in codes(assert_case_postconditions(case(), obs))


def test_conflict_cannot_be_cleared_by_unrelated_target_read():
    first = event(code='DATASET_CHANGED', arguments={'employee_id': 'one'})
    second = replace(event(sequence=2, arguments={'employee_id': 'other'}),
        started_at='2026-10-15T00:00:02Z', finished_at='2026-10-15T00:00:03Z')
    assert 'DATASET_REREAD_REQUIRED' in codes(assert_trace_policy(case(), (first, second)))


@pytest.mark.parametrize('job', [False, True])
def test_real_mysql_receipt_job_audit_facts_and_corruption(job):
    import os
    from datetime import datetime
    from sqlalchemy import update
    from app.evaluation.fixtures import evaluation_database, seed_case
    from app.persistence.models import ChangeLog, DatasetState, OperationReceipt, StoreProfile, SyncJob

    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；真实回执审计验收未执行')
    c, template = operation_evidence(job=job)
    with evaluation_database(url) as factory:
        seed_case(factory, c)
        with independent_reader(url) as reader:
            before = reader.snapshot()
        now = datetime(2026, 10, 15)
        with factory.begin() as writer:
            writer.execute(update(DatasetState).where(DatasetState.id == 1).values(data_version=2))
            if job:
                writer.add(SyncJob(**template.after.rows('sync_job')[0], created_at=now, updated_at=now))
            log_values = deepcopy(template.after.rows('change_log')[0])
            if not job:
                profile = next(r for r in before.rows('store_profile') if r['department_id'] == 'store_people')
                fields = ('is_store', 'store_code', 'notes')
                log_values['before_data'] = {k: profile[k] for k in fields}
                log_values['after_data'] = {**log_values['before_data'], 'notes': 'synthetic-changed'}
                writer.execute(update(StoreProfile).where(StoreProfile.department_id == 'store_people').values(notes='synthetic-changed'))
            writer.add(ChangeLog(**log_values, committed_at=now))
            writer.add(OperationReceipt(**template.after.rows('operation_receipt')[0],
                idempotency_key='synthetic-key', request_hash='a' * 64, created_at=now, updated_at=now))
        with independent_reader(url) as reader:
            after = reader.snapshot()
        obs = EvaluationEvidence(before, after, template.context, template.fake_writes, template.output)
        assert assert_case_postconditions(c, obs) == []
        with factory.begin() as writer:
            if job:
                writer.execute(update(SyncJob).where(SyncJob.id == 'job-eval').values(status='future_unknown'))
            else:
                writer.execute(update(ChangeLog).where(ChangeLog.id == 91).values(actor='other-actor'))
        with independent_reader(url) as reader:
            obs.after = reader.snapshot()
        assert ('JOB_MISMATCH' if job else 'AUDIT_MISSING') in codes(assert_case_postconditions(c, obs))


def test_all_expected_keys_execute_even_when_another_key_is_unknown():
    c = replace(case(), expected_state={'unsupported_key': True, 'data_version': 3, 'dataset_epoch': 'test-wrong'})
    failures = assert_case_postconditions(c, evidence())
    assert len(failures) == 3
    assert codes(failures) == {'UNSUPPORTED_PREDICATE', 'VERSION_MISMATCH'}


def test_all_forbidden_keys_execute_even_when_first_is_unknown():
    obs = evidence()
    obs.after._tables['dataset_state'][0]['data_version'] = 3
    obs.fake_writes = {'count': 1, 'by_method': {'DELETE': 1}}
    c = replace(case(), forbidden_effects=({'predicate': 'unsupported'},
        {'predicate': 'data_version_unchanged'}, {'predicate': 'no_feishu_writes'}))
    failures = assert_forbidden_effects(c, obs)
    assert len(failures) == 3
    assert codes(failures) == {'UNSUPPORTED_PREDICATE', 'FORBIDDEN_EFFECT'}


@pytest.mark.parametrize('url', ['sqlite://', 'mysql+pymysql://local/production', 'mysql://local/x_test', 'invalid'])
def test_reader_rejects_unsafe_targets_before_engine_creation(url, monkeypatch):
    import app.evaluation.evidence as module
    def forbidden_engine(*args, **kwargs):
        pytest.fail('不安全目标不能创建连接')
    monkeypatch.setattr(module, 'create_mysql_engine', forbidden_engine)
    with pytest.raises(ValueError, match='EVALUATION_TEST_DATABASE_REQUIRED'):
        with independent_reader(url):
            pass


def test_row_condition_invalid_literal_cannot_pass_as_zero_matches():
    c = replace(case(), expected_state={'rows': [
        {'table': 'employee', 'where': {'id': {'fake': 'identifier'}}, 'equals': {}, 'count': 0}]})
    assert 'INVALID_PREDICATE' in codes(assert_case_postconditions(c, evidence()))


def test_reader_database_exception_exposes_only_safe_fixed_message(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.evaluation.evidence import EvidenceReadError
    import app.evaluation.evidence as module
    class BrokenEngine:
        def connect(self):
            raise OperationalError('SELECT synthetic-private-data', {}, Exception('synthetic-password'))
        def dispose(self):
            pass
    monkeypatch.setattr(module, 'create_mysql_engine', lambda url: BrokenEngine())
    with pytest.raises(EvidenceReadError) as caught:
        with independent_reader('mysql+pymysql://local/x_test'):
            pass
    assert str(caught.value) == 'EVALUATION_EVIDENCE_READ_FAILED'
    assert caught.value.__suppress_context__ is True


def test_report_trace_preserves_generated_operation_id_and_does_not_turn_unknown_error_into_success():
    identifier = 'op_' + 'a' * 32
    captured = capture_worker_output(AgentRun('', (event(operation_id=identifier, code='synthetic-unknown'),), {}))
    assert captured.redacted_run.trace[0].operation_id == identifier
    assert captured.redacted_run.trace[0].result_code == 'REDACTED_CODE'
    assert captured.redacted_run.trace[0].arguments == {}


@pytest.mark.parametrize('field,value', [('sync_quality', 'future_unknown'), ('sync_quality', 'partial')])
def test_unrecognized_or_partial_quality_cannot_be_promoted_to_resolved(field, value):
    obs = evidence()
    obs.after._tables['employee'][0][field] = value
    obs.output = capture_worker_output(AgentRun('', (), {'execution': 'verified', 'fact_quality': 'resolved'}))
    assert 'TERMINAL_MISMATCH' in codes(assert_case_postconditions(case(), obs))


@pytest.mark.parametrize('table,status', [('operation_receipt', 'succeeded'), ('operation_receipt', 'queued'), ('sync_job', 'submitted')])
def test_status_enums_are_not_interchangeable_between_receipt_and_job(table, status):
    c, obs = operation_evidence(job=True)
    obs.after._tables[table][0]['status'] = status
    obs.output = capture_worker_output(replace(obs.output._run, terminal_observation={'execution': 'verified'}))
    assert 'TERMINAL_MISMATCH' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('name', ['PRIMARY_STORE', 'NOT_IN_STORE'])
@pytest.mark.parametrize('variant', ['empty', 'unrelated', 'not_found'])
def test_fix1_official_read_cases_require_successful_target_completion(name, variant):
    c = case(name)
    obs = evidence(c)
    trace = () if variant == 'empty' else (event(arguments={
        'employee_id': 'unrelated' if variant == 'unrelated' else c.expected_state['employee_id']},
        code='NOT_FOUND' if variant == 'not_found' else None),)
    obs.output = capture_worker_output(AgentRun('完成', trace, {}))
    failures = (assert_case_postconditions(c, obs) + assert_forbidden_effects(c, obs)
                + assert_trace_policy(c, trace))
    assert 'MISSING_EVIDENCE' in codes(failures)


def read_wire(c):
    expected = c.expected_state
    employee = {'id': expected['employee_id'], **{k: deepcopy(expected[k]) for k in (
        'primary_department_id', 'primary_store_id', 'primary_store_status', 'store_ids')}}
    version = {k: c.fixture['dataset_state'][k] for k in ('dataset_epoch', 'data_version')}
    return {'operation_id': None, 'data': {'data': employee, 'meta': version},
            'observation': {'execution': 'submitted', 'fact_quality': 'resolved', **version},
            'audit': {}, 'error': None}


def attach_read_proofs(obs, events, wires):
    from app.evaluation.evidence import capture_mcp_response
    obs.output = capture_worker_output(AgentRun('', tuple(events), {}))
    obs.mcp_responses = tuple(capture_mcp_response(e, w, is_error=False) for e, w in zip(events, wires))
    return obs


@pytest.mark.parametrize('name', ['PRIMARY_STORE', 'NOT_IN_STORE'])
@pytest.mark.parametrize('field,wrong', [('primary_department_id', 'wrong'), ('primary_store_id', 'wrong'),
    ('primary_store_status', 'unknown'), ('store_ids', []), ('id', 'unrelated')])
def test_fix1_correct_database_does_not_mask_wrong_mcp_target_data(name, field, wrong):
    c = case(name)
    wire = read_wire(c)
    wire['data']['data'][field] = wrong
    obs = attach_read_proofs(evidence(c), [event(arguments={'employee_id': c.expected_state['employee_id']})], [wire])
    assert assert_case_postconditions(c, obs)


@pytest.mark.parametrize('split_ownership', [False, True])
def test_fix1_actual_audit_binds_owning_receipt_target_even_when_optional(split_ownership):
    c, obs = operation_evidence()
    before = obs.before.rows('store_profile')[0]
    after = obs.after.rows('store_profile')[0]
    after['is_store'] = False
    log = obs.after.rows('change_log')[0]
    log['before_data'] = {k: before[k] for k in ('is_store', 'store_code', 'notes')}
    log['after_data'] = {k: after[k] for k in ('is_store', 'store_code', 'notes')}
    first = replace(obs.output._run.trace[0], arguments={'changes': [{'department_id': 'store_river', 'is_store': False}]})
    trace = [first]
    if split_ownership:
        other = deepcopy(obs.after.rows('operation_receipt')[0])
        other['operation_id'] = 'op-other'
        other['result_summary'] = {'audit_ids': []}
        obs.after.rows('operation_receipt').append(other)
        trace.append(replace(first, sequence=2, operation_id='op-other',
            arguments={'changes': [{'department_id': 'store_people', 'is_store': False}]},
            started_at='2026-10-15T00:00:02Z', finished_at='2026-10-15T00:00:03Z'))
    obs.output = capture_worker_output(AgentRun('', tuple(trace), {}))
    c = replace(c, expected_state={**c.expected_state, 'operation': {
        **c.expected_state['operation'], 'count': 2 if split_ownership else 1, 'audit_required': False}})
    assert 'AUDIT_MISSING' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('name', ['PRIMARY_STORE', 'NOT_IN_STORE'])
@pytest.mark.parametrize('tool', ['get_employee', 'list_store_employees', 'list_employees'])
def test_fix1_legitimate_complete_target_read_paths_pass_without_fixed_sequence(name, tool):
    c = case(name)
    if tool == 'list_employees':
        c = replace(c, allowed_tools=(*c.allowed_tools, tool))
    wire = read_wire(c)
    if tool != 'get_employee':
        wire['data']['data'] = [wire['data']['data']]
    arguments = ({'employee_id': c.expected_state['employee_id']} if tool == 'get_employee' else
                 {'store_id': c.expected_state['store_ids'][0]} if tool == 'list_store_employees' else {})
    target = replace(event(tool, arguments=arguments, sequence=2),
        started_at='2026-10-15T00:00:02Z', finished_at='2026-10-15T00:00:03Z')
    # 前置无关合法读取不影响成功；只要求完成目标，不固定工具序列。
    pre = event('get_department', arguments={'department_id': 'hq'})
    obs = evidence(c)
    from app.evaluation.evidence import capture_mcp_response
    obs.output = capture_worker_output(AgentRun('', (pre, target), {}))
    obs.mcp_responses = (capture_mcp_response(target, wire, is_error=False),)
    assert assert_case_postconditions(c, obs) == []
    assert assert_trace_policy(c, obs.output._run.trace) == []
    assert assert_forbidden_effects(c, obs) == []


@pytest.mark.parametrize('part,field', [('data', 'id'), ('data', 'primary_department_id'),
    ('data', 'primary_store_id'), ('data', 'primary_store_status'), ('data', 'store_ids'),
    ('meta', 'dataset_epoch'), ('meta', 'data_version'), ('observation', 'execution'),
    ('observation', 'fact_quality'), ('observation', 'dataset_epoch'), ('observation', 'data_version')])
def test_fix1_required_mcp_completion_fields_cannot_be_missing(part, field):
    c = case()
    wire = read_wire(c)
    target = wire['observation'] if part == 'observation' else wire['data'][part]
    del target[field]
    obs = attach_read_proofs(evidence(c), [event(arguments={'employee_id': c.expected_state['employee_id']})], [wire])
    assert 'MISSING_EVIDENCE' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('part,field,value', [('meta', 'data_version', 99), ('meta', 'dataset_epoch', 'test-other'),
    ('observation', 'data_version', 99), ('observation', 'dataset_epoch', 'test-other')])
def test_fix1_response_generation_and_version_match_independent_snapshot(part, field, value):
    c = case()
    wire = read_wire(c)
    target = wire['observation'] if part == 'observation' else wire['data']['meta']
    target[field] = value
    obs = attach_read_proofs(evidence(c), [event(arguments={'employee_id': c.expected_state['employee_id']})], [wire])
    assert 'VERSION_MISMATCH' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('variant', ['duplicate_target', 'unrelated_row', 'wrong_store', 'duplicate_store_ids'])
def test_fix1_list_result_must_contain_unique_complete_target(variant):
    c = case()
    wire = read_wire(c)
    row = wire['data']['data']
    wire['data']['data'] = [row]
    arguments = {'store_id': 'store_people'}
    if variant == 'duplicate_target': wire['data']['data'].append(deepcopy(row))
    if variant == 'unrelated_row': row['id'] = 'unrelated'
    if variant == 'wrong_store': arguments['store_id'] = 'other_store'
    if variant == 'duplicate_store_ids': row['store_ids'].append(row['store_ids'][0])
    obs = attach_read_proofs(evidence(c), [event('list_store_employees', arguments=arguments)], [wire])
    assert assert_case_postconditions(c, obs)


@pytest.mark.parametrize('variant', ['sdk_error', 'tool_error', 'missing_error', 'missing_body', 'response_none',
    'trace_failure', 'target_none', 'unconfirmed', 'unknown_quality', 'no_proof', 'event_mismatch', 'duplicate_proof'])
def test_fix1_trusted_response_binding_and_success_are_required(variant):
    from app.evaluation.evidence import capture_mcp_response
    c = case()
    wire = read_wire(c)
    target = event(arguments={'employee_id': c.expected_state['employee_id']})
    if variant == 'tool_error': wire['error'] = {'code': 'NOT_FOUND'}
    if variant == 'missing_error': del wire['error']
    if variant == 'missing_body': del wire['data']['data']
    if variant == 'response_none': wire = None
    if variant == 'target_none': wire['data']['data'] = None
    if variant == 'trace_failure': target = replace(target, result_code='NOT_FOUND')
    if variant == 'unconfirmed': wire['observation']['execution'] = 'unconfirmed'
    if variant == 'unknown_quality': wire['observation']['fact_quality'] = 'unknown'
    obs = evidence(c)
    obs.output = capture_worker_output(AgentRun('', (target,), {}))
    proof = capture_mcp_response(target, wire, is_error=variant == 'sdk_error')
    obs.mcp_responses = (proof,)
    if variant == 'no_proof': obs.mcp_responses = None
    if variant == 'event_mismatch':
        obs.output = capture_worker_output(AgentRun('', (replace(target, arguments={'employee_id': 'other'}),), {}))
    if variant == 'duplicate_proof': obs.mcp_responses = (proof, proof)
    assert assert_case_postconditions(c, obs)


def test_fix1_mcp_response_scanned_before_allowlist_and_public_summary_contains_no_body():
    c = case()
    wire = read_wire(c)
    wire['data']['data']['name'] = 'synthetic-private-person'
    wire['data']['data']['access_token'] = 'synthetic-response-secret'
    obs = attach_read_proofs(evidence(c), [event(arguments={'employee_id': c.expected_state['employee_id']})], [wire])
    assert 'SENSITIVE_LEAK' in codes(assert_case_postconditions(c, obs))
    assert 'name' not in obs.mcp_responses[0]._employees[0]
    assert 'access_token' not in obs.mcp_responses[0]._employees[0]
    assert 'synthetic-response-secret' not in repr(obs.summary())
    assert 'synthetic-private-person' not in repr(obs.mcp_responses)
    assert obs.summary()['sensitive_leak'] is True


def test_fix1_mcp_response_capture_is_a_detached_snapshot():
    c = case()
    wire = read_wire(c)
    obs = attach_read_proofs(evidence(c), [event(arguments={'employee_id': c.expected_state['employee_id']})], [wire])
    wire['data']['data']['store_ids'].clear()
    assert assert_case_postconditions(c, obs) == []


def test_fix1_audit_cannot_have_two_owning_receipts():
    c, obs = operation_evidence()
    before, after = obs.before.rows('store_profile')[0], obs.after.rows('store_profile')[0]
    after['is_store'] = False
    log = obs.after.rows('change_log')[0]
    log['before_data'] = {k: before[k] for k in ('is_store', 'store_code', 'notes')}
    log['after_data'] = {k: after[k] for k in ('is_store', 'store_code', 'notes')}
    second = deepcopy(obs.after.rows('operation_receipt')[0])
    second['operation_id'] = 'op-second'
    obs.after.rows('operation_receipt').append(second)
    first = obs.output._run.trace[0]
    trace = (first, replace(first, sequence=2, operation_id='op-second',
        started_at='2026-10-15T00:00:02Z', finished_at='2026-10-15T00:00:03Z'))
    obs.output = capture_worker_output(AgentRun('', trace, {}))
    c = replace(c, expected_state={**c.expected_state, 'operation': {
        **c.expected_state['operation'], 'count': 2, 'audit_required': False}})
    assert 'AUDIT_MISSING' in codes(assert_case_postconditions(c, obs))


def test_fix1_existing_audit_target_is_checked_even_when_final_state_has_no_net_change():
    c, obs = operation_evidence()
    trace = (replace(obs.output._run.trace[0], arguments={
        'changes': [{'department_id': 'store_river', 'is_store': False}]}),)
    obs.output = capture_worker_output(AgentRun('', trace, {}))
    c = replace(c, expected_state={**c.expected_state, 'operation': {
        **c.expected_state['operation'], 'audit_required': False}})
    assert 'AUDIT_MISSING' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('variant',['new_final','old_only','late_failure','late_missing_proof','unrelated_failure','late_list_failure'])
def test_task4_completion_uses_last_target_read_without_erasing_history(variant):
    c,obs=case(),evidence()
    target={'employee_id':c.expected_state['employee_id']}
    first=event(arguments=target)
    old=read_wire(c)
    final=deepcopy(old)
    if variant in {'new_final','old_only'}:
        obs.after._tables['dataset_state'][0]['data_version']=2
        final['data']['meta']['data_version']=2
        final['observation']['data_version']=2
    events,wires=[first],[old]
    if variant=='late_list_failure':
        first=event('list_store_employees',arguments={'store_id':'store_people'})
        old['data']['data']=[old['data']['data']]
        events,wires=[first],[old]
    if variant!='old_only':
        late=event(tool=first.tool_name,arguments=first.arguments,sequence=2)
        if variant=='unrelated_failure': late=replace(late,arguments={'employee_id':'unrelated'})
        if variant not in {'new_final','late_missing_proof'}:
            late=replace(late,result_code='NOT_FOUND')
            final={'operation_id':None,'data':None,'observation':{},'audit':{},'error':{'code':'NOT_FOUND'}}
        events.append(late)
        if variant!='late_missing_proof': wires.append(final)
    attach_read_proofs(obs,events,wires)
    failures=assert_case_postconditions(c,obs)
    if variant in {'new_final','unrelated_failure'}:
        assert failures==[]
    else:
        assert failures


def test_task4_historical_response_leak_is_still_hard_failure():
    c,obs=case(),evidence()
    old,new=read_wire(c),read_wire(c)
    old['data']['private']='Bearer synthetic-private-canary'
    attach_read_proofs(obs,[event(arguments={'employee_id':c.expected_state['employee_id']},sequence=n) for n in (1,2)],[old,new])
    assert 'SENSITIVE_LEAK' in codes(assert_case_postconditions(c,obs))


@pytest.mark.parametrize('tool,defaults', [
    ('list_store_employees', {'membership': 'all', 'include_inactive': False, 'limit': 20}),
    ('list_employees', {'include_descendants': False, 'include_inactive': False,
                        'department_id': None, 'store_id': None, 'primary_store_id': None, 'limit': 20}),
])
def test_task4_equivalent_default_query_cannot_hide_later_failure(tool, defaults):
    c, obs = case(), evidence()
    c = replace(c, allowed_tools=(*c.allowed_tools, tool))
    arguments = {'store_id': 'store_people'} if tool == 'list_store_employees' else {}
    first = event(tool, arguments=arguments)
    late = event(tool, sequence=2, arguments={**arguments, **defaults})
    late = replace(late, result_code='NOT_FOUND')
    wire = read_wire(c)
    wire['data']['data'] = [wire['data']['data']]
    failed = {'operation_id': None, 'data': None, 'observation': {}, 'audit': {},
              'error': {'code': 'NOT_FOUND'}}
    attach_read_proofs(obs, [first, late], [wire, failed])
    assert 'MISSING_EVIDENCE' in codes(assert_case_postconditions(c, obs))


@pytest.mark.parametrize('variant', ['next_page', 'restart_empty', 'failed_page', 'old_page'])
def test_task4_list_completion_preserves_target_across_valid_following_pages(variant):
    c, obs = case(), evidence()
    first = event('list_store_employees', arguments={'store_id': 'store_people'})
    late = event('list_store_employees', sequence=2,
                 arguments={'store_id': 'store_people', 'cursor': 'synthetic-page-2'})
    wire, page = read_wire(c), read_wire(c)
    wire['data']['data'] = [wire['data']['data']]
    page['data']['data'] = [{**page['data']['data'], 'id': 'other_employee'}]
    if variant == 'restart_empty':
        late = replace(late, arguments={'store_id': 'store_people'})
    if variant == 'failed_page':
        late = replace(late, result_code='NOT_FOUND')
        page['error'] = {'code': 'NOT_FOUND'}
    if variant == 'old_page':
        page['data']['meta']['data_version'] = 0
    attach_read_proofs(obs, [first, late], [wire, page])
    failures = assert_case_postconditions(c, obs)
    assert not failures if variant == 'next_page' else failures


def test_task4_pagination_cannot_erase_intermediate_direct_target_failure():
    c, obs = case(), evidence()
    first = event('list_store_employees', arguments={'store_id': 'store_people'})
    direct = replace(event(sequence=2, arguments={'employee_id': c.expected_state['employee_id']}),
                     result_code='NOT_FOUND')
    late = event('list_store_employees', sequence=3,
                 arguments={'store_id': 'store_people', 'cursor': 'synthetic-page-2'})
    wire, page = read_wire(c), read_wire(c)
    wire['data']['data'] = [wire['data']['data']]
    page['data']['data'] = [{**page['data']['data'], 'id': 'other_employee'}]
    failed = {'operation_id': None, 'data': None, 'observation': {}, 'audit': {},
              'error': {'code': 'NOT_FOUND'}}
    attach_read_proofs(obs, [first, direct, late], [wire, failed, page])
    assert 'MISSING_EVIDENCE' in codes(assert_case_postconditions(c, obs))


def test_task4_pagination_cannot_erase_failure_from_another_target_query():
    c, obs = case(), evidence()
    events = [event('list_store_employees', sequence=1, arguments={'store_id': 'store_people'}),
              event('list_store_employees', sequence=2, arguments={'store_id': 'store_river'}),
              event('list_store_employees', sequence=3, arguments={'store_id': 'store_river', 'cursor': 'river-2'}),
              event('list_store_employees', sequence=4, arguments={'store_id': 'store_people', 'cursor': 'people-2'})]
    events[2] = replace(events[2], result_code='NOT_FOUND')
    wire, page = read_wire(c), read_wire(c)
    wire['data']['data'] = [wire['data']['data']]
    page['data']['data'] = [{**page['data']['data'], 'id': 'other_employee'}]
    failed = {'operation_id': None, 'data': None, 'observation': {}, 'audit': {},
              'error': {'code': 'NOT_FOUND'}}
    attach_read_proofs(obs, events, [wire, wire, failed, page])
    assert 'MISSING_EVIDENCE' in codes(assert_case_postconditions(c, obs))
