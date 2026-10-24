"""写入、冲突恢复与待核实场景的独立证据负向测试。"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation.cases import load_case
from app.evaluation.assertions import assert_case_postconditions, assert_forbidden_effects
from app.evaluation.evidence import (BUSINESS_TABLES, DatabaseSnapshot, EvaluationEvidence,
                                     capture_worker_output, capture_mcp_response)
from app.evaluation.models import AgentRun, AgentRunContext, ToolTraceEvent


def observation(name='ORG_AGENT_VERSION_CONFLICT'):
    case = load_case(Path(__file__).parent / 'cases' / (name + '.yaml'))
    tables = {name: [] for name in BUSINESS_TABLES}
    for section, table in [('departments', 'department'), ('employees', 'employee'),
                           ('employee_departments', 'employee_department'), ('employee_stores', 'employee_store'),
                           ('store_profiles', 'store_profile')]:
        tables[table] = deepcopy(case.fixture[section])
    tables['dataset_state'] = [deepcopy(case.fixture['dataset_state'])]
    evidence = EvaluationEvidence(DatabaseSnapshot(tables), DatabaseSnapshot(deepcopy(tables)),
        AgentRunContext('test-scenario', case.case_id, 'evaluation-ci', 'test'),
        {'count': 0, 'by_method': {}}, capture_worker_output(AgentRun('', (), {})))
    return case, evidence


@pytest.mark.parametrize('mutation', [False, True])
def test_scope_row_guard_compares_full_private_source_values(mutation):
    case, evidence = observation()
    case = replace(case, forbidden_effects=({'predicate': 'rows_unchanged', 'table': 'employee',
                                            'where': {'id': 'eval_employee_primary'}},))
    if mutation:
        evidence.after._tables['employee'][0]['name'] = 'private-canary'
    failures = assert_forbidden_effects(case, evidence)
    assert bool(failures) == mutation
    assert 'private-canary' not in repr(failures)


@pytest.mark.parametrize('rule', [
    {'predicate': 'rows_unchanged', 'table': 'employee', 'where': {}},
    {'predicate': 'rows_unchanged', 'table': 'employee', 'where': {'id': 42}},
    {'predicate': 'rows_unchanged', 'table': 'employee', 'where': {'name': 'private-canary'}},
    {'predicate': 'rows_unchanged', 'table': 'made_up', 'where': {'id': 'anything'}},
    {'predicate': 'rows_unchanged', 'table': 'employee', 'where': {'id': 'missing'}},
])
def test_scope_guard_rejects_unsupported_invalid_or_missing_scope(rule):
    case, evidence = observation()
    assert assert_forbidden_effects(replace(case, forbidden_effects=(rule,)), evidence)


def _event(sequence, name, arguments, code=None):
    return ToolTraceEvent(sequence, name, arguments, code, None,
                          f'2026-10-16T00:00:0{sequence}Z', f'2026-10-16T00:00:0{sequence}Z')


@pytest.mark.parametrize('variant', ['valid', 'no_conflict', 'wrong_target', 'old_read', 'missing_store',
                                     'wrong_store', 'write_after_conflict', 'unbound_proof'])
def test_conflict_requires_real_target_conflict_and_fresh_preservation_proof(variant):
    case, evidence = observation()
    case = replace(case, expected_state={'conflict_recovery': case.expected_state['conflict_recovery']})
    evidence.after._tables['dataset_state'][0]['data_version'] = 2
    evidence.after._tables['store_profile'][0]['store_code'] = 'EVAL_CONCURRENT'
    conflict = _event(1, 'apply_store_changes', {'changes': [{'department_id': 'store_people',
                      'is_store': True, 'store_code': 'EVAL_WORKER'}]}, 'DATASET_CHANGED')
    read = _event(2, 'get_store', {'store_id': 'store_people'})
    wire = {'operation_id': None, 'data': {'data': {'id': 'store_people', 'store_code': 'EVAL_CONCURRENT'},
            'meta': {'dataset_epoch': 'test-eval-primary-store', 'data_version': 2}}, 'audit': {}, 'error': None,
            'observation': {'execution': 'submitted', 'fact_quality': 'resolved',
                            'dataset_epoch': 'test-eval-primary-store', 'data_version': 2}}
    if variant == 'no_conflict':
        conflict = replace(conflict, result_code='NOT_FOUND')
    if variant == 'wrong_target':
        conflict = replace(conflict, arguments={'changes': [{'department_id': 'store_river'}]})
    if variant == 'old_read':
        wire['data']['meta']['data_version'] = 1
    if variant == 'missing_store':
        wire['data']['data'] = None
    if variant == 'wrong_store':
        wire['data']['data']['store_code'] = 'EVAL_WORKER'
    events = [conflict, read]
    if variant == 'write_after_conflict':
        events.append(_event(3, 'apply_store_changes', {}, 'DATASET_CHANGED'))
    evidence.output = capture_worker_output(AgentRun('', tuple(events), {}))
    proof = capture_mcp_response(read, wire, is_error=False)
    if variant == 'unbound_proof':
        proof._event = replace(read, arguments={'store_id': 'store_river'})
    evidence.mcp_responses = (proof,)
    failures = assert_case_postconditions(case, evidence)
    assert not failures if variant == 'valid' else failures


@pytest.mark.parametrize('quality', ['unknown', 'resolved'])
def test_pending_employee_read_matches_target_quality_instead_of_global_quality(quality):
    case, evidence = observation('ORG_AGENT_PERMISSION_SHRINK')
    expected = {key: value for key, value in case.expected_state.items()
                if key in {'employee_id', 'primary_department_id', 'primary_store_id', 'primary_store_status',
                           'store_ids', 'read_completion'}}
    case = replace(case, expected_state=expected)
    employee = evidence.after._tables['employee'][0]
    employee['sync_quality'], employee['primary_store_status'] = 'pending_verification', 'unknown'
    evidence.after._tables['employee_store'] = []
    evidence.after._tables['pending_fact'] = [{'object_type': 'employee', 'source_id': 'eval_user'}]
    event = _event(1, 'get_employee', {'employee_id': 'eval_user'})
    wire = {'operation_id': None, 'data': {'data': {'id': 'eval_user',
            **{key: expected[key] for key in ('primary_department_id', 'primary_store_id',
                                             'primary_store_status', 'store_ids')}},
            'meta': {'dataset_epoch': 'test-eval-permission', 'data_version': 1}}, 'audit': {}, 'error': None,
            'observation': {'execution': 'partial', 'fact_quality': quality,
                            'dataset_epoch': 'test-eval-permission', 'data_version': 1}}
    epoch = case.fixture['dataset_state']['dataset_epoch']
    wire['data']['meta']['dataset_epoch'] = wire['observation']['dataset_epoch'] = epoch
    evidence.output = capture_worker_output(AgentRun('', (event,), {}))
    evidence.mcp_responses = (capture_mcp_response(event, wire, is_error=False),)
    failures = assert_case_postconditions(case, evidence)
    assert not failures if quality == 'unknown' else failures


def test_mixed_quality_list_uses_whole_page_quality_and_still_checks_target_facts():
    case = load_case(Path(__file__).parent / 'cases/ORG_AGENT_READ_PRIMARY_STORE.yaml')
    _, evidence = observation()
    evidence.context = replace(evidence.context, case_id=case.case_id)
    evidence.after._tables['employee'].append({'id': 'eval_other', 'sync_quality': 'complete',
        'primary_store_status': 'unknown'})
    event = _event(1, 'list_store_employees', {'store_id': 'store_people'})
    target = {'id': 'eval_employee_primary', **{key: case.expected_state[key] for key in
        ('primary_department_id', 'primary_store_id', 'primary_store_status', 'store_ids')}}
    wire = {'operation_id': None, 'error': None, 'audit': {},
        'data': {'data': [target, {'id': 'eval_other'}],
                 'meta': {'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}},
        'observation': {'execution': 'submitted', 'fact_quality': 'unknown',
                        'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}}
    evidence.output = capture_worker_output(AgentRun('', (event,), {}))
    evidence.mcp_responses = (capture_mcp_response(event, wire, is_error=False),)
    assert assert_case_postconditions(case, evidence) == []
    target['primary_store_id'] = 'store_river'
    evidence.mcp_responses = (capture_mcp_response(event, wire, is_error=False),)
    assert assert_case_postconditions(case, evidence)


@pytest.mark.parametrize('store_quality, fact_quality', [
    ('complete', 'resolved'), ('partial', 'partial'), ('incomplete', 'unknown'),
    ('unknown', 'unknown'), ('pending_verification', 'unknown'), ('pending', 'unknown'),
    ('inconsistent', 'inconsistent'),
])
def test_store_employee_list_includes_queried_store_quality(store_quality, fact_quality):
    case = load_case(Path(__file__).parent / 'cases/ORG_AGENT_READ_PRIMARY_STORE.yaml')
    _, evidence = observation()
    evidence.context = replace(evidence.context, case_id=case.case_id)
    for department in evidence.after._tables['department']:
        department['sync_quality'] = store_quality if department['id'] == 'store_people' else 'complete'
    target = {'id': 'eval_employee_primary', **{key: case.expected_state[key] for key in
        ('primary_department_id', 'primary_store_id', 'primary_store_status', 'store_ids')}}
    event = _event(1, 'list_store_employees', {'store_id': 'store_people'})
    wire = {'operation_id': None, 'error': None, 'audit': {},
        'data': {'data': [target], 'meta': {'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}},
        'observation': {'execution': 'submitted', 'fact_quality': fact_quality,
                        'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}}
    evidence.output = capture_worker_output(AgentRun('', (event,), {}))
    evidence.mcp_responses = (capture_mcp_response(event, wire, is_error=False),)
    assert assert_case_postconditions(case, evidence) == []
    wire['observation']['fact_quality'] = 'unknown' if fact_quality == 'resolved' else 'resolved'
    evidence.mcp_responses = (capture_mcp_response(event, wire, is_error=False),)
    assert assert_case_postconditions(case, evidence)


@pytest.mark.parametrize('table, identifier', [('employee', 'eval_employee_primary'),
    ('department', 'people_service'), ('department', 'store_people')])
@pytest.mark.parametrize('quality', ['unknown', 'resolved'])
@pytest.mark.parametrize('raw_quality', ['future_unknown', 'resolved', 'not_in_store', 'inactive'])
def test_future_quality_is_never_promoted_to_resolved(table, identifier, quality, raw_quality):
    case, evidence = observation('ORG_AGENT_READ_PRIMARY_STORE')
    for snapshot in (evidence.before, evidence.after):
        for row in snapshot._tables[table]:
            if row['id'] == identifier:
                row['sync_quality'] = raw_quality
    event = _event(1, 'list_store_employees', {'store_id': 'store_people'})
    target = {'id': 'eval_employee_primary', **{key: case.expected_state[key] for key in
        ('primary_department_id', 'primary_store_id', 'primary_store_status', 'store_ids')}}
    wire = {'operation_id': None, 'error': None, 'audit': {},
        'data': {'data': [target], 'meta': {'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}},
        'observation': {'execution': 'submitted', 'fact_quality': quality,
                        'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}}
    evidence.output = capture_worker_output(AgentRun('', (event,), {}))
    evidence.mcp_responses = (capture_mcp_response(event, wire, is_error=False),)
    failures = assert_case_postconditions(case, evidence)
    assert not failures if quality == 'unknown' else failures


@pytest.mark.parametrize('variant', ['valid', 'missing_preview', 'late_preview', 'failed_preview',
    'different_changes', 'different_version', 'different_epoch', 'missing_proof', 'unbound_proof',
    'missing_data', 'empty_changes', 'wrong_result', 'unconfirmed'])
def test_apply_requires_trusted_successful_matching_preview(variant):
    case, evidence = observation('ORG_AGENT_APPLY_STORE')
    case = replace(case, expected_state={'preview_apply': case.expected_state['preview_apply']})
    changes = [{'department_id': 'people_service', 'is_store': True, 'store_code': 'EVAL_SERVICE'}]
    preview = _event(1, 'preview_store_changes', {'changes': changes, 'expected_version': 1})
    apply = replace(_event(2, 'apply_store_changes', {'changes': changes,
        'expected_epoch': 'test-eval-primary-store', 'expected_version': 1}), operation_id='op_' + 'a' * 32)
    if variant == 'late_preview':
        preview, apply = replace(preview, sequence=3), replace(apply, sequence=1)
    if variant == 'failed_preview':
        preview = replace(preview, result_code='VALIDATION_ERROR')
    if variant == 'different_changes':
        preview = replace(preview, arguments={'changes': [{'department_id': 'store_river', 'is_store': False}],
                                             'expected_version': 1})
    if variant == 'different_version':
        apply = replace(apply, arguments={**apply.arguments, 'expected_version': 2})
    if variant == 'different_epoch':
        apply = replace(apply, arguments={**apply.arguments, 'expected_epoch': 'test-another'})
    events = (apply,) if variant == 'missing_preview' else tuple(sorted((preview, apply), key=lambda e: e.sequence))
    evidence.output = capture_worker_output(AgentRun('', events, {}))
    evidence.after._tables['operation_receipt'] = [{'operation_id': apply.operation_id,
        'capability': 'apply_store_changes', 'status': 'submitted', 'job_id': None,
        'result_summary': {}, **{key: getattr(evidence.context, key) for key in
        ('actor_id', 'environment', 'run_id', 'case_id')}}]
    wire = {'operation_id': None, 'error': None, 'audit': {},
        'data': {'data': {'data_version': 1, 'affected_employee_count': 1,
                         'changes': [{**changes[0], 'notes': None}]},
                 'meta': {'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}},
        'observation': {'execution': 'submitted', 'fact_quality': 'resolved',
                        'dataset_epoch': 'test-eval-primary-store', 'data_version': 1}}
    if variant == 'missing_data':
        wire['data']['data'] = None
    if variant == 'empty_changes':
        wire['data']['data']['changes'] = []
    if variant == 'wrong_result':
        wire['data']['data']['changes'][0]['store_code'] = 'EVAL_OTHER'
    if variant == 'unconfirmed':
        wire['observation']['execution'] = 'unconfirmed'
    proof = capture_mcp_response(preview, wire, is_error=variant == 'failed_preview')
    if variant == 'unbound_proof':
        proof._event = replace(preview, sequence=99)
    evidence.mcp_responses = () if variant == 'missing_proof' else (proof,)
    failures = assert_case_postconditions(case, evidence)
    assert not failures if variant == 'valid' else failures
