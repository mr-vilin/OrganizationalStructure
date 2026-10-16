"""固定夹具驱动的确定性硬门槛。Worker 声明只能被核验，不能充当实际事实。"""
from datetime import datetime
import json

from app.evaluation.evidence import (
    BUSINESS_TABLES, EvaluationEvidence, DatabaseSnapshot, CapturedOutput, McpResponseEvidence,
    capture_worker_output,
)
from app.evaluation.models import AgentRun, ToolTraceEvent
from app.mcp.policy import TOOL_LEVELS
from app.persistence.models import Base

_MESSAGES = {
    'UNSUPPORTED_PREDICATE': '不支持的断言条件。', 'INVALID_PREDICATE': '断言条件格式不合法。',
    'MISSING_EVIDENCE': '缺少可信独立证据。', 'FACT_MISMATCH': '独立事实与固定期望不符。',
    'VERSION_MISMATCH': '数据世代或版本与期望不符。', 'FORBIDDEN_EFFECT': '发生禁止副作用。',
    'RECEIPT_MISSING': '操作回执缺失或关联不完整。', 'IDENTITY_MISMATCH': '操作身份关联不符。',
    'AUDIT_MISSING': '审计证据缺失或关联不符。', 'JOB_MISMATCH': '任务证据或终态不符。',
    'TERMINAL_MISMATCH': '结构化终态声明与独立证据不符。', 'SENSITIVE_LEAK': '检测到敏感出站材料。',
    'TOOL_FORBIDDEN': '调用了未授权工具。', 'TRACE_INVALID': '工具轨迹结构或时序不合法。',
    'TOOL_BUDGET_EXCEEDED': '工具调用超出预算。',
    'DATASET_REREAD_REQUIRED': '数据冲突后缺少针对目标的新读取。',
}


class AssertionFailure(Exception):
    """公开失败只使用固定消息与允许的谓词名称，不回显外部值。"""
    def __init__(self, code: str, predicate: str = 'evidence'):
        self.code = code if code in _MESSAGES else 'INVALID_PREDICATE'
        self.message = _MESSAGES[self.code]
        self.evidence = {'predicate': predicate if predicate in _LABELS else 'unsupported'}
        super().__init__(self.message)


_READ = {'employee_id', 'primary_department_id', 'primary_store_id', 'primary_store_status', 'store_ids'}
_EXPECTED = _READ | {'dataset_epoch', 'data_version', 'version_delta', 'rows', 'operation', 'execution', 'fact_quality', 'read_completion', 'conflict_recovery', 'preview_apply'}
_FORBIDDEN = {'business_tables_unchanged', 'data_version_unchanged', 'no_new_operation_receipts',
              'no_new_sync_jobs', 'no_new_change_logs', 'no_feishu_writes', 'pending_protected', 'rows_unchanged'}
_LABELS = _EXPECTED | _FORBIDDEN | {'evidence', 'trace', 'privacy', 'identity', 'terminal', 'unsupported'}
# 行级谓词只接受这些实际持久字段；不支持任意 SQL、JSON 路径或自然语言条件。
_ROW_FIELDS = {
    'department': {'id', 'parent_id', 'status', 'sync_quality', 'is_virtual_root'},
    'employee': {'id', 'status', 'sync_quality', 'primary_department_id', 'primary_store_status'},
    'employee_department': {'employee_id', 'department_id', 'is_primary', 'active'},
    'employee_store': {'employee_id', 'store_id', 'is_primary', 'path'},
    'store_profile': {'department_id', 'is_store', 'store_code'},
    'pending_fact': {'object_type', 'source_id', 'error_code'},
    'dataset_state': {'id', 'dataset_epoch', 'data_version', 'initialization_status', 'coverage_status'},
    'sync_job': {'id', 'type', 'root_department_id', 'requested_by', 'status', 'phase',
                 'attempt', 'execution_count', 'retry_count', 'total_count', 'success_count', 'failure_count', 'error_code'},
    'sync_job_detail': {'id', 'job_id', 'object_type', 'object_id', 'status', 'error_code', 'attempt', 'change_log_id'},
    'change_log': {'id', 'object_type', 'object_id', 'source', 'actor', 'job_id'},
    'operation_receipt': {'operation_id', 'capability', 'actor_type', 'actor_id', 'environment', 'run_id',
                          'case_id', 'status', 'job_id', 'before_epoch', 'before_version',
                          'committed_epoch', 'committed_version', 'error_code'},
    'feishu_connection': {'id', 'status', 'coverage_status'},
    'event_inbox': {'event_id', 'event_type', 'object_id', 'status', 'attempts'},
}
_PK = {'operation_receipt': ('operation_id',), 'sync_job': ('id',), 'change_log': ('id',)}


def _need(condition, code='MISSING_EVIDENCE', label='evidence'):
    if not condition:
        raise AssertionFailure(code, label)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=lambda v: v.isoformat())


def _same(left, right):
    return _canonical(left) == _canonical(right)


def _rows(snapshot, table):
    _need(isinstance(snapshot, DatabaseSnapshot) and table in snapshot._tables)
    rows = snapshot.rows(table)
    _need(isinstance(rows, list) and all(isinstance(r, dict) for r in rows))
    return rows


def _field(row, key):
    _need(key in row)
    return row[key]


def _state(snapshot):
    rows = [r for r in _rows(snapshot, 'dataset_state') if _field(r, 'id') == 1]
    _need(len(rows) == 1)
    return rows[0]


def _version(snapshot):
    state = _state(snapshot)
    epoch, version = _field(state, 'dataset_epoch'), _field(state, 'data_version')
    _need(isinstance(epoch, str) and type(version) is int and version >= 0)
    return epoch, version


def _new(obs, table):
    keys = _PK[table]
    before = {tuple(_field(r, k) for k in keys) for r in _rows(obs.before, table)}
    return [r for r in _rows(obs.after, table) if tuple(_field(r, k) for k in keys) not in before]


def _validate_evidence(case, obs):
    _need(isinstance(obs, EvaluationEvidence))
    _need(isinstance(obs.before, DatabaseSnapshot) and isinstance(obs.after, DatabaseSnapshot))
    context = obs.context
    _need(context.environment == 'test' and context.case_id == case.case_id
          and isinstance(context.run_id, str) and context.run_id.startswith(('test-', 'test_'))
          and bool(context.actor_id), 'IDENTITY_MISMATCH', 'identity')


def _collect(action, failures):
    try:
        action()
    except AssertionFailure as failure:
        failures.append(failure)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        failures.append(AssertionFailure('INVALID_PREDICATE'))


def _employee(expected, obs):
    _need(isinstance(expected.get('employee_id'), str), 'INVALID_PREDICATE', 'employee_id')
    rows = [r for r in _rows(obs.after, 'employee') if _field(r, 'id') == expected['employee_id']]
    _need(len(rows) == 1, 'FACT_MISMATCH', 'employee_id')
    return rows[0]


def _read_condition(key, value, expected, obs):
    employee = _employee(expected, obs)
    employee_id = expected['employee_id']
    if key == 'employee_id':
        return
    if key in {'primary_department_id', 'primary_store_status'}:
        _need(_same(_field(employee, key), value), 'FACT_MISMATCH', key)
        if key == 'primary_department_id':
            relations = [r for r in _rows(obs.after, 'employee_department')
                         if _field(r, 'employee_id') == employee_id and _field(r, 'active')
                         and _field(r, 'is_primary')]
            _need([_field(r, 'department_id') for r in relations] == ([] if value is None else [value]),
                  'FACT_MISMATCH', key)
        return
    stores = [r for r in _rows(obs.after, 'employee_store') if _field(r, 'employee_id') == employee_id]
    if key == 'primary_store_id':
        primary = [_field(r, 'store_id') for r in stores if _field(r, 'is_primary')]
        _need(primary == ([] if value is None else [value]), 'FACT_MISMATCH', key)
    else:
        _need(isinstance(value, list) and all(type(x) is str for x in value), 'INVALID_PREDICATE', key)
        actual = [_field(r, 'store_id') for r in stores]
        _need(len(value) == len(set(value)) and len(actual) == len(set(actual))
              and set(actual) == set(value), 'FACT_MISMATCH', key)


def _read_completion(value, expected, obs, case):
    _need(value == {'predicate': 'employee_attribution'}, 'INVALID_PREDICATE', 'read_completion')
    _need(_READ <= expected.keys(), 'INVALID_PREDICATE', 'read_completion')
    _need(isinstance(obs.mcp_responses, tuple) and bool(obs.mcp_responses), label='read_completion')
    _need(isinstance(obs.output, CapturedOutput), label='read_completion')
    trace = obs.output._run.trace
    target = expected['employee_id']
    by_sequence = {}
    target_queries = []
    list_tools = {'list_employees', 'list_store_employees'}
    def query(event):
        defaults = ({'membership': 'all', 'include_inactive': False}
                    if event.tool_name == 'list_store_employees' else
                    {'department_id': None, 'include_descendants': False, 'store_id': None,
                     'primary_store_id': None, 'include_inactive': False})
        return (event.tool_name, {k: v for k, v in {**defaults, **event.arguments}.items()
                if k not in {'dataset_epoch', 'data_version', 'cursor', 'page_token', 'limit'}})
    for response in obs.mcp_responses:
        _need(isinstance(response, McpResponseEvidence), label='read_completion')
        event = response._event
        # 全部历史 proof 仍必须真实且唯一地绑定可信 trace。
        _need(sum(e == event for e in trace) == 1 and event.sequence not in by_sequence,
              label='read_completion')
        by_sequence[event.sequence] = response
        if event.tool_name in list_tools and any(r.get('id') == target for r in response._employees):
            target_queries.append(query(event))
    related = []
    for event in trace:
        if event.tool_name not in case.allowed_tools:
            continue
        direct = event.tool_name == 'get_employee' and event.arguments.get('employee_id') == target
        listed = event.tool_name in list_tools and query(event) in target_queries
        if direct or listed:
            related.append(event)
    _need(bool(related), label='read_completion')
    related.sort(key=lambda item: item.sequence)
    target_reads = [item for item in related if item.sequence in by_sequence and any(
        row.get('id') == target for row in by_sequence[item.sequence]._employees)]
    _need(bool(target_reads), label='read_completion')
    event = target_reads[-1]
    # 后续成功分页可不含目标，但任何相关查询的晚失败都不能被另一组分页掩盖。
    completion_pages = [item for item in related if item.sequence >= event.sequence]
    for page in completion_pages:
        proof = by_sequence.get(page.sequence)
        _need(proof is not None and proof._valid and proof._success, label='read_completion')
        if page.tool_name == 'get_employee' or not page.arguments.get('cursor'):
            _need(any(row.get('id') == target for row in proof._employees), label='read_completion')
        _need('execution' in proof._observation, label='read_completion')
        _need(proof._observation.get('execution') in {'submitted', 'verified', 'partial'},
              'TERMINAL_MISMATCH', 'read_completion')
        for key, actual in zip(('dataset_epoch', 'data_version'), _version(obs.after)):
            for part in (proof._meta, proof._observation):
                _need(key in part, label='read_completion')
                _need(_same(part[key], actual), 'VERSION_MISMATCH', 'read_completion')
    response = by_sequence.get(event.sequence)
    _need(response is not None and response._success, label='read_completion')
    rows = [r for r in response._employees if r.get('id') == target]
    _need(response._valid and len(rows) == 1, label='read_completion')
    row = rows[0]
    _need({'id', 'primary_department_id', 'primary_store_id', 'primary_store_status', 'store_ids'} <= row.keys(),
          label='read_completion')
    if event.tool_name == 'list_store_employees':
        store = event.arguments.get('store_id')
        _need(store in expected['store_ids'] and event.arguments.get('membership', 'all') in {'all', 'primary'},
              'FACT_MISMATCH', 'read_completion')
        if event.arguments.get('membership') == 'primary':
            _need(store == expected['primary_store_id'], 'FACT_MISMATCH', 'read_completion')
    for key in ('primary_department_id', 'primary_store_id', 'primary_store_status'):
        _need(_same(row[key], expected[key]), 'FACT_MISMATCH', 'read_completion')
    stores = row['store_ids']
    _need(isinstance(stores, list) and all(type(item) is str for item in stores), label='read_completion')
    _need(len(stores) == len(set(stores)) and set(stores) == set(expected['store_ids']),
          'FACT_MISMATCH', 'read_completion')
    for version_key, actual in zip(('dataset_epoch', 'data_version'), _version(obs.after)):
        for part in (response._meta, response._observation):
            _need(version_key in part, label='read_completion')
            _need(_same(part[version_key], actual), 'VERSION_MISMATCH', 'read_completion')
    _need({'execution', 'fact_quality'} <= response._observation.keys(), label='read_completion')
    _need(response._observation['execution'] in {'submitted', 'verified', 'partial'}
          and response._observation['fact_quality'] == _employee_page_quality(response._employees, obs, event),
          'TERMINAL_MISMATCH', 'read_completion')
    # 固定预期同时再比独立DB，不能因API与一个错误预期相同而跳过真实事实。
    for key in _READ:
        _read_condition(key, expected[key], expected, obs)


_SYNC_QUALITY = {'complete': 'resolved', 'partial': 'partial', 'inconsistent': 'inconsistent',
                 'pending_verification': 'unknown'}
_PRIMARY_QUALITY = {'resolved': 'resolved', 'not_in_store': 'resolved', 'inactive': 'resolved',
                    'inconsistent': 'inconsistent', 'unknown': 'unknown'}


def _aggregate_read_quality(qualities, base='resolved'):
    for quality in ('inconsistent', 'unknown', 'partial'):
        if quality in qualities:
            return quality
    return base


def _employee_read_quality(employee_id, obs):
    """独立核验目标质量；全局 partial 不会使 pending 目标被误报为已确认。"""
    state = _state(obs.after)
    quality = ('partial' if _rows(obs.after, 'pending_fact') or _field(state, 'coverage_status') == 'incomplete'
               else 'resolved' if _field(state, 'initialization_status') == 'complete'
               and _field(state, 'coverage_status') == 'complete' else 'unknown')
    employee = _employee({'employee_id': employee_id}, obs)
    qualities = [_SYNC_QUALITY.get(_field(employee, 'sync_quality'), 'unknown'),
                 _PRIMARY_QUALITY.get(_field(employee, 'primary_store_status'), 'unknown')]
    departments = {_field(row, 'department_id') for row in _rows(obs.after, 'employee_department')
                   if _field(row, 'employee_id') == employee_id and _field(row, 'active')}
    qualities += [_SYNC_QUALITY.get(_field(row, 'sync_quality'), 'unknown') for row in _rows(obs.after, 'department')
                  if _field(row, 'id') in departments]
    return _aggregate_read_quality(qualities, quality)


def _employee_page_quality(rows, obs, event):
    """独立聚合整页和所查询门店的事实质量。"""
    qualities = []
    for row in rows:
        _need(isinstance(row.get('id'), str), label='read_completion')
        qualities.append(_employee_read_quality(row['id'], obs))
    if event.tool_name == 'list_store_employees':
        stores = [row for row in _rows(obs.after, 'department')
                  if _field(row, 'id') == event.arguments.get('store_id')]
        _need(len(stores) == 1, label='read_completion')
        target_quality = _field(stores[0], 'sync_quality')
        qualities.append(_SYNC_QUALITY.get(target_quality, 'unknown'))
    return _aggregate_read_quality(qualities)


def _preview_apply(value, obs):
    """成功写入必须由同一世代/版本、相同变更的真实成功预览先行。"""
    _need(value == {'predicate': 'matching_store_changes'}, 'INVALID_PREDICATE', 'preview_apply')
    _need(isinstance(obs.output, CapturedOutput) and isinstance(obs.mcp_responses, tuple), label='preview_apply')
    trace = obs.output._run.trace
    applies = [event for event in trace if event.tool_name == 'apply_store_changes' and event.result_code is None]
    _need(bool(applies), label='preview_apply')
    def changes(event):
        rows = event.arguments.get('changes')
        _need(isinstance(rows, list) and bool(rows) and all(isinstance(row, dict) for row in rows),
              label='preview_apply')
        return sorted(_canonical(row) for row in rows)
    for apply in applies:
        previews = [event for event in trace if event.tool_name == 'preview_store_changes'
                    and event.sequence < apply.sequence and event.result_code is None
                    and changes(event) == changes(apply)
                    and _same(event.arguments.get('expected_version'), apply.arguments.get('expected_version'))]
        _need(bool(previews), label='preview_apply')
        preview = max(previews, key=lambda event: event.sequence)
        proofs = [proof for proof in obs.mcp_responses if isinstance(proof, McpResponseEvidence)
                  and proof._event == preview]
        _need(len(proofs) == 1 and sum(event == preview for event in trace) == 1, label='preview_apply')
        proof = proofs[0]
        _need(proof._valid and proof._success and isinstance(proof._preview, dict)
              and proof._observation.get('execution') in {'submitted', 'verified', 'partial'},
              label='preview_apply')
        requested = apply.arguments['changes']
        returned = proof._preview['changes']
        _need(len(returned) == len(requested) and len({row['department_id'] for row in returned}) == len(returned),
              label='preview_apply')
        for change in requested:
            matches = [row for row in returned if row['department_id'] == change.get('department_id')]
            _need(len(matches) == 1, label='preview_apply')
            for key, expected in change.items():
                if key == 'store_code' and isinstance(expected, str):
                    expected = expected.strip() or None
                _need(key in matches[0] and _same(matches[0][key], expected), 'FACT_MISMATCH', 'preview_apply')
        _need(_same(proof._preview['data_version'], apply.arguments.get('expected_version')),
              'VERSION_MISMATCH', 'preview_apply')
        for key, expected in [('dataset_epoch', apply.arguments.get('expected_epoch')),
                              ('data_version', apply.arguments.get('expected_version'))]:
            for part in (proof._meta, proof._observation):
                _need(expected is not None and key in part and _same(part[key], expected),
                      'VERSION_MISMATCH', 'preview_apply')


def _conflict_recovery(value, obs):
    _need(isinstance(value, dict) and set(value) == {'store_id', 'store_code'}
          and all(isinstance(item, str) and item for item in value.values()), 'INVALID_PREDICATE', 'conflict_recovery')
    _need(isinstance(obs.output, CapturedOutput) and isinstance(obs.mcp_responses, tuple), label='conflict_recovery')
    target = value['store_id']
    trace = obs.output._run.trace
    conflicts = [event for event in trace if event.tool_name == 'apply_store_changes'
                 and event.result_code in {'DATASET_CHANGED', 'VERSION_CONFLICT'}
                 and any(isinstance(change, dict) and change.get('department_id') == target
                         for change in event.arguments.get('changes', []))]
    _need(bool(conflicts), label='conflict_recovery')
    conflict = conflicts[0]
    _need(not any(event.sequence > conflict.sequence and event.tool_name in _WRITE_TOOLS for event in trace),
          'FORBIDDEN_EFFECT', 'conflict_recovery')
    reads = [event for event in trace if event.sequence > conflict.sequence
             and ((event.tool_name == 'get_store' and event.arguments.get('store_id') == target)
                  or (event.tool_name == 'get_department' and event.arguments.get('department_id') == target))]
    _need(bool(reads), label='conflict_recovery')
    event = max(reads, key=lambda item: item.sequence)
    _need(not any(event.arguments.get(key) is not None for key in
                  ('cursor', 'dataset_epoch', 'data_version', 'expected_epoch', 'expected_version')),
          'DATASET_REREAD_REQUIRED', 'conflict_recovery')
    proofs = [proof for proof in obs.mcp_responses if isinstance(proof, McpResponseEvidence) and proof._event == event]
    _need(len(proofs) == 1 and sum(item == event for item in trace) == 1, label='conflict_recovery')
    proof = proofs[0]
    _need(proof._valid and proof._success, label='conflict_recovery')
    stores = [row for row in proof._stores if row.get('id') == target]
    profiles = [row for row in _rows(obs.after, 'store_profile') if _field(row, 'department_id') == target]
    _need(len(stores) == len(profiles) == 1
          and stores[0].get('store_code') == value['store_code'] == _field(profiles[0], 'store_code'),
          'FACT_MISMATCH', 'conflict_recovery')
    for key, actual in zip(('dataset_epoch', 'data_version'), _version(obs.after)):
        for part in (proof._meta, proof._observation):
            _need(key in part, label='conflict_recovery')
            _need(_same(part[key], actual), 'VERSION_MISMATCH', 'conflict_recovery')
    _need(proof._observation.get('execution') in {'submitted', 'verified'}
          and proof._observation.get('fact_quality') == 'resolved', 'TERMINAL_MISMATCH', 'conflict_recovery')


def _validate_row_literals(table, values, label):
    _need(isinstance(table, str) and table in _ROW_FIELDS, 'UNSUPPORTED_PREDICATE', label)
    _need(isinstance(values, dict), 'INVALID_PREDICATE', label)
    _need(set(values) <= _ROW_FIELDS[table], 'UNSUPPORTED_PREDICATE', label)
    for field, literal in values.items():
        column = Base.metadata.tables[table].columns[field]
        valid = (literal is None and column.nullable) or type(literal) is column.type.python_type
        if field == 'path':
            valid = isinstance(literal, list) and all(type(item) is str for item in literal)
        _need(valid, 'INVALID_PREDICATE', label)


def _rows_unchanged(rule, obs):
    _need(set(rule) == {'predicate', 'table', 'where'}, 'INVALID_PREDICATE', 'rows_unchanged')
    table, where = rule['table'], rule['where']
    _validate_row_literals(table, where, 'rows_unchanged')
    _need(bool(where), 'INVALID_PREDICATE', 'rows_unchanged')
    rows = [[row for row in _rows(snapshot, table)
             if all(_same(_field(row, key), value) for key, value in where.items())]
            for snapshot in (obs.before, obs.after)]
    _need(bool(rows[0]), label='rows_unchanged')
    _need(sorted(map(_canonical, rows[0])) == sorted(map(_canonical, rows[1])),
          'FORBIDDEN_EFFECT', 'rows_unchanged')



def _row_conditions(value, obs):
    _need(isinstance(value, list) and bool(value), 'INVALID_PREDICATE', 'rows')
    for rule in value:
        _need(isinstance(rule, dict) and set(rule) == {'table', 'where', 'equals', 'count'}, 'INVALID_PREDICATE', 'rows')
        table, where, equals, count = (rule[k] for k in ('table', 'where', 'equals', 'count'))
        _need(isinstance(table, str) and table in _ROW_FIELDS, 'UNSUPPORTED_PREDICATE', 'rows')
        _need(isinstance(where, dict) and isinstance(equals, dict) and type(count) is int and count >= 0,
              'INVALID_PREDICATE', 'rows')
        _validate_row_literals(table, where, 'rows')
        _validate_row_literals(table, equals, 'rows')
        _need(bool(where) or bool(equals), 'INVALID_PREDICATE', 'rows')
        found = [r for r in _rows(obs.after, table) if all(_same(_field(r, k), v) for k, v in where.items())]
        _need(len(found) == count and all(all(_same(_field(r, k), v) for k, v in equals.items()) for r in found),
              'FACT_MISMATCH', 'rows')


def _linked_receipts(obs):
    receipts = _new(obs, 'operation_receipt')
    _need(isinstance(obs.output, CapturedOutput))
    trace = obs.output._run.trace
    for receipt in receipts:
        _need(all(_field(receipt, k) == getattr(obs.context, k) for k in ('actor_id', 'environment', 'run_id', 'case_id')),
              'IDENTITY_MISMATCH', 'identity')
        _need(any(e.operation_id == _field(receipt, 'operation_id') and e.tool_name == _field(receipt, 'capability')
                  for e in trace), 'RECEIPT_MISSING', 'operation')
    for event in trace:
        if event.tool_name in _WRITE_TOOLS and event.result_code is None:
            _need(bool(event.operation_id), 'RECEIPT_MISSING', 'operation')
        if event.operation_id:
            candidates = [r for r in _rows(obs.after, 'operation_receipt') if _field(r, 'operation_id') == event.operation_id]
            _need(len(candidates) == 1, 'RECEIPT_MISSING', 'operation')
            receipt = candidates[0]
            _need(all(_field(receipt, k) == getattr(obs.context, k) for k in ('actor_id', 'environment', 'run_id', 'case_id')),
                  'IDENTITY_MISMATCH', 'identity')
    return receipts


def _operation(value, obs):
    required = {'capability', 'status', 'count', 'audit_required', 'job_required'}
    _need(isinstance(value, dict) and set(value) == required, 'INVALID_PREDICATE', 'operation')
    _need(value['capability'] in {'apply_store_changes', 'request_sync', 'retry_sync_job'}
          and value['status'] in {'recorded', 'accepted', 'submitted', 'failed'}
          and type(value['count']) is int and value['count'] > 0
          and type(value['audit_required']) is bool and type(value['job_required']) is bool,
          'INVALID_PREDICATE', 'operation')
    receipts = [r for r in _linked_receipts(obs) if _field(r, 'capability') == value['capability']]
    _need(len(receipts) == value['count'], 'RECEIPT_MISSING', 'operation')
    epoch, version = _version(obs.after)
    before_epoch, before_version = _version(obs.before)
    for receipt in receipts:
        _need(_field(receipt, 'status') == value['status'], 'TERMINAL_MISMATCH', 'operation')
        _need(_field(receipt, 'before_epoch') == before_epoch
              and type(_field(receipt, 'before_version')) is int
              and before_version <= receipt['before_version'], 'VERSION_MISMATCH', 'operation')
        if receipt['status'] in {'submitted', 'accepted'}:
            committed = _field(receipt, 'committed_version')
            _need(_field(receipt, 'committed_epoch') == epoch and type(committed) is int
                  and 0 <= committed <= version
                  and (before_epoch != epoch or receipt['before_version'] <= committed), 'VERSION_MISMATCH', 'operation')
        job_id = _field(receipt, 'job_id')
        if value['job_required']:
            jobs = [r for r in _rows(obs.after, 'sync_job') if _field(r, 'id') == job_id]
            _need(len(jobs) == 1, 'JOB_MISMATCH', 'operation')
            job = jobs[0]
            _need(_field(job, 'requested_by') == obs.context.actor_id, 'IDENTITY_MISMATCH', 'identity')
            if receipt['status'] == 'submitted':
                _need(_field(job, 'status') == 'succeeded', 'JOB_MISMATCH', 'operation')
        if value['audit_required']:
            summary = _field(receipt, 'result_summary')
            _need(isinstance(summary, dict) and isinstance(summary.get('audit_ids'), list)
                  and bool(summary['audit_ids']), 'AUDIT_MISSING', 'operation')
            ids = summary['audit_ids']
            _need(len(ids) == len(set(ids)), 'AUDIT_MISSING', 'operation')
            logs = {str(_field(r, 'id')): r for r in _new(obs, 'change_log')}
            for audit_id in ids:
                log = logs.get(str(audit_id))
                _need(log is not None, 'AUDIT_MISSING', 'operation')
                if job_id:
                    _need(_field(log, 'job_id') == job_id, 'AUDIT_MISSING', 'operation')
                else:
                    _need(_field(log, 'actor') == obs.context.actor_id and _field(log, 'source') == 'admin'
                          and _field(log, 'object_type') == 'store', 'AUDIT_MISSING', 'operation')
                    events = [e for e in obs.output._run.trace if e.operation_id == receipt['operation_id']
                              and e.tool_name == 'apply_store_changes']
                    targets = {change['department_id'] for e in events
                               for change in e.arguments.get('changes', [])
                               if isinstance(change, dict) and isinstance(change.get('department_id'), str)}
                    _need(_field(log, 'object_id') in targets, 'AUDIT_MISSING', 'operation')



def _audit_store_changes(obs):
    """真实门店业务变化必须有可连续追溯的审计链；无变化不制造审计要求。"""
    before = {_field(r, 'department_id'): r for r in _rows(obs.before, 'store_profile')}
    after = {_field(r, 'department_id'): r for r in _rows(obs.after, 'store_profile')}
    receipts = _new(obs, 'operation_receipt')
    if not receipts:
        return  # 只读场景由 business_tables_unchanged 捕获非法变化。
    apply_receipts = [r for r in receipts if _field(r, 'capability') == 'apply_store_changes']
    if not apply_receipts:
        return
    owners = {}
    for receipt in apply_receipts:
        summary = _field(receipt, 'result_summary')
        if isinstance(summary, dict) and isinstance(summary.get('audit_ids'), list):
            for audit_id in summary['audit_ids']:
                owners.setdefault(str(audit_id), []).append(receipt)
    store_logs = [r for r in _new(obs, 'change_log') if _field(r, 'object_type') == 'store']
    for log in store_logs:
        identifier = _field(log, 'object_id')
        owning = owners.get(str(_field(log, 'id')), [])
        _need(len(owning) == 1, 'AUDIT_MISSING', 'operation')
        owner = owning[0]
        requests = [e for e in obs.output._run.trace if e.operation_id == owner['operation_id']
                    and e.tool_name == 'apply_store_changes' and e.result_code is None]
        _need(bool(requests), 'AUDIT_MISSING', 'operation')
        for request in requests:
            changes = request.arguments.get('changes')
            _need(isinstance(changes, list) and any(isinstance(c, dict) and c.get('department_id') == identifier
                                                   for c in changes), 'AUDIT_MISSING', 'operation')
        _need(_field(log, 'actor') == obs.context.actor_id and _field(log, 'source') == 'admin',
              'AUDIT_MISSING', 'operation')
    for identifier in before.keys() | after.keys():
        if _same(before.get(identifier), after.get(identifier)):
            continue
        logs = [r for r in store_logs if _field(r, 'object_id') == identifier]
        _need(bool(logs) and identifier in after, 'AUDIT_MISSING', 'operation')
        fields = ('is_store', 'store_code', 'notes')
        previous = {k: _field(before[identifier], k) for k in fields} if identifier in before else {
            'is_store': False, 'store_code': None, 'notes': None}
        for log in sorted(logs, key=lambda r: _field(r, 'id')):
            _need(_field(log, 'actor') == obs.context.actor_id
                  and _field(log, 'source') == 'admin' and _same(_field(log, 'before_data'), previous),
                  'AUDIT_MISSING', 'operation')
            previous = _field(log, 'after_data')
        _need(_same(previous, {k: _field(after[identifier], k) for k in fields}), 'AUDIT_MISSING', 'operation')


def _terminal(obs):
    state = _state(obs.after)
    quality = 'resolved'
    if _field(state, 'initialization_status') != 'complete' or _field(state, 'coverage_status') not in {'complete', 'incomplete'}:
        quality = 'unknown'
    qualities = [_field(r, 'sync_quality') for t in ('employee', 'department') for r in _rows(obs.after, t)]
    primary_qualities = [_field(r, 'primary_store_status') for r in _rows(obs.after, 'employee')]
    if 'inconsistent' in qualities:
        quality = 'inconsistent'
    elif any(q not in {'complete', 'partial', 'pending_verification', 'inconsistent'} for q in qualities):
        quality = 'unknown'
    elif (_rows(obs.after, 'pending_fact') or 'pending_verification' in qualities or 'partial' in qualities
          or _field(state, 'coverage_status') == 'incomplete'):
        quality = 'partial'
    if quality == 'resolved' and any(q not in {'resolved', 'not_in_store', 'inactive'} for q in primary_qualities):
        quality = 'inconsistent' if 'inconsistent' in primary_qualities else 'unknown'
    receipts = _new(obs, 'operation_receipt')
    statuses = []
    for receipt in receipts:
        status = _field(receipt, 'status')
        receipt_status = status
        if receipt_status not in {'recorded', 'accepted', 'submitted', 'failed'}:
            status = '__unknown_receipt__'
        job_id = _field(receipt, 'job_id')
        if job_id:
            jobs = [r for r in _rows(obs.after, 'sync_job') if _field(r, 'id') == job_id]
            _need(len(jobs) == 1, 'JOB_MISMATCH', 'terminal')
            job_status = _field(jobs[0], 'status')
            if receipt_status == 'submitted':
                status = job_status if job_status in {'queued', 'running', 'succeeded', 'failed'} else '__unknown_job__'
            elif receipt_status == 'accepted' and job_status == 'running':
                status = 'running'
            details = [r for r in _rows(obs.after, 'sync_job_detail') if _field(r, 'job_id') == job_id]
            if any(_field(r, 'status') == 'failed' for r in details) or _field(jobs[0], 'failure_count') > 0:
                quality = 'partial'
        statuses.append({'recorded': 'unconfirmed', 'accepted': 'accepted', 'queued': 'accepted',
                         'running': 'running', 'submitted': 'submitted', 'succeeded': 'submitted',
                         'failed': 'failed'}.get(status, 'unconfirmed'))
    execution = next((s for s in ('failed', 'unconfirmed', 'running', 'accepted') if s in statuses),
                     'submitted' if statuses else 'verified')
    if quality == 'partial' and execution in {'submitted', 'verified'}:
        execution = 'partial'
    elif quality in {'unknown', 'inconsistent'} and execution in {'submitted', 'verified'}:
        execution = 'unconfirmed'
    return execution, quality


def _check_claim(obs):
    _need(isinstance(obs.output, CapturedOutput))
    _need(not obs.output.sensitive_leak, 'SENSITIVE_LEAK', 'privacy')
    for response in obs.mcp_responses or ():
        _need(isinstance(response, McpResponseEvidence))
        _need(not response.sensitive_leak, 'SENSITIVE_LEAK', 'privacy')
    claimed = obs.output._run.terminal_observation
    _need(isinstance(claimed, dict), 'TERMINAL_MISMATCH', 'terminal')
    actual = dict(zip(('execution', 'fact_quality'), _terminal(obs)))
    for key in ('execution', 'fact_quality'):
        if key in claimed:
            compatible = key == 'execution' and claimed[key] == 'verified' and actual[key] == 'submitted'
            _need(claimed[key] == actual[key] or compatible, 'TERMINAL_MISMATCH', 'terminal')
    for key, value in zip(('dataset_epoch', 'data_version'), _version(obs.after)):
        if key in claimed:
            _need(_same(claimed[key], value), 'VERSION_MISMATCH', 'terminal')


def assert_case_postconditions(case, observation) -> list[AssertionFailure]:
    failures = []
    _collect(lambda: _validate_evidence(case, observation), failures)
    if failures:
        return failures
    obs = observation
    _collect(lambda: _check_claim(obs), failures)
    _collect(lambda: _linked_receipts(obs), failures)
    _collect(lambda: _audit_store_changes(obs), failures)
    expected = case.expected_state
    if not isinstance(expected, dict) or not expected:
        return failures + [AssertionFailure('INVALID_PREDICATE')]
    def check(key, value):
        _need(key in _EXPECTED, 'UNSUPPORTED_PREDICATE')
        if key in _READ:
            _read_condition(key, value, expected, obs)
        elif key == 'rows':
            _row_conditions(value, obs)
        elif key == 'operation':
            _operation(value, obs)
        elif key == 'read_completion':
            _read_completion(value, expected, obs, case)
        elif key == 'conflict_recovery':
            _conflict_recovery(value, obs)
        elif key == 'preview_apply':
            _preview_apply(value, obs)
        elif key in {'execution', 'fact_quality'}:
            actual = _terminal(obs)[0 if key == 'execution' else 1]
            _need(actual == value, 'TERMINAL_MISMATCH', key)
        else:
            epoch, version = _version(obs.after)
            if key == 'version_delta':
                prior_epoch, prior_version = _version(obs.before)
                _need(type(value) is int and value >= 0, 'INVALID_PREDICATE', key)
                _need(epoch == prior_epoch and version - prior_version == value, 'VERSION_MISMATCH', key)
            else:
                _need(_same(epoch if key == 'dataset_epoch' else version, value), 'VERSION_MISMATCH', key)
    for key, value in expected.items():
        _collect(lambda: check(key, value), failures)
    return failures


def _pending_protected(rule, obs):
    _need(set(rule) == {'predicate', 'employee_ids', 'department_ids'}, 'INVALID_PREDICATE', 'pending_protected')
    _need(any(rule[k] for k in ('employee_ids', 'department_ids')), 'INVALID_PREDICATE', 'pending_protected')
    for table, key in [('employee', 'employee_ids'), ('department', 'department_ids')]:
        identifiers = rule[key]
        _need(isinstance(identifiers, list) and all(type(v) is str for v in identifiers)
              and len(identifiers) == len(set(identifiers)), 'INVALID_PREDICATE', 'pending_protected')
        for identifier in identifiers:
            before = [r for r in _rows(obs.before, table) if _field(r, 'id') == identifier]
            after = [r for r in _rows(obs.after, table) if _field(r, 'id') == identifier]
            _need(len(before) == len(after) == 1, 'FORBIDDEN_EFFECT', 'pending_protected')
            # 不可读不意味着离职/删除。只有质量与时间允许变化，其余原始事实保持。
            ignored = {'sync_quality', 'last_seen_at'} | ({'primary_store_status'} if table == 'employee' else set())
            _need(_field(after[0], 'sync_quality') == 'pending_verification'
                  and _same({k:v for k,v in before[0].items() if k not in ignored},
                            {k:v for k,v in after[0].items() if k not in ignored}), 'FORBIDDEN_EFFECT', 'pending_protected')
            if table == 'employee':
                for relation in ('employee_department',):
                    rows = [[r for r in _rows(snap, relation) if _field(r, 'employee_id') == identifier]
                            for snap in (obs.before, obs.after)]
                    _need(sorted(map(_canonical, rows[0])) == sorted(map(_canonical, rows[1])),
                          'FORBIDDEN_EFFECT', 'pending_protected')


def assert_forbidden_effects(case, observation) -> list[AssertionFailure]:
    failures = []
    _collect(lambda: _validate_evidence(case, observation), failures)
    if failures:
        return failures
    obs = observation
    def check(rule):
        _need(isinstance(rule, dict) and 'predicate' in rule, 'INVALID_PREDICATE')
        name = rule['predicate']
        _need(isinstance(name, str) and name in _FORBIDDEN, 'UNSUPPORTED_PREDICATE')
        if name == 'pending_protected':
            return _pending_protected(rule, obs)
        if name == 'rows_unchanged':
            return _rows_unchanged(rule, obs)
        _need(set(rule) == {'predicate'}, 'INVALID_PREDICATE', name)
        if name == 'business_tables_unchanged':
            for table in BUSINESS_TABLES:
                _need(sorted(map(_canonical, _rows(obs.before, table))) == sorted(map(_canonical, _rows(obs.after, table))),
                      'FORBIDDEN_EFFECT', name)
        elif name == 'data_version_unchanged':
            _need(_version(obs.before) == _version(obs.after), 'FORBIDDEN_EFFECT', name)
        elif name == 'no_feishu_writes':
            evidence = obs.fake_writes
            _need(isinstance(evidence, dict) and set(evidence) == {'count', 'by_method'})
            count, methods = evidence['count'], evidence['by_method']
            _need(type(count) is int and count >= 0 and isinstance(methods, dict))
            _need(all(isinstance(k, str) and k in {'POST', 'PUT', 'PATCH', 'DELETE', 'OTHER'}
                      and type(v) is int and v > 0 for k,v in methods.items()) and sum(methods.values()) == count)
            _need(count == 0, 'FORBIDDEN_EFFECT', name)
        else:
            table = {'no_new_operation_receipts': 'operation_receipt', 'no_new_sync_jobs': 'sync_job',
                     'no_new_change_logs': 'change_log'}[name]
            _need(not _new(obs, table), 'FORBIDDEN_EFFECT', name)
    if not isinstance(case.forbidden_effects, (tuple, list)):
        return failures + [AssertionFailure('INVALID_PREDICATE')]
    for rule in case.forbidden_effects:
        _collect(lambda: check(rule), failures)
    return failures


_READ_TOOLS = {'get_system_status', 'get_department', 'get_employee', 'list_stores', 'get_store',
               'list_store_employees', 'find_departments', 'list_employees'}
_WRITE_TOOLS = {'apply_store_changes', 'request_sync', 'retry_sync_job'}


def assert_trace_policy(case, trace) -> list[AssertionFailure]:
    failures = []
    def check():
        _need(isinstance(trace, (tuple, list)), 'TRACE_INVALID', 'trace')
        _need(all(isinstance(e, ToolTraceEvent) for e in trace), 'TRACE_INVALID', 'trace')
        _need(len(trace) <= case.max_tool_calls, 'TOOL_BUDGET_EXCEEDED', 'trace')
        _need(not capture_worker_output(AgentRun('', tuple(trace), {})).sensitive_leak, 'SENSITIVE_LEAK', 'privacy')
        previous_end = None
        conflict = None
        first_start = None
        for index, event in enumerate(trace, 1):
            _need(type(event.sequence) is int and event.sequence == index and isinstance(event.arguments, dict), 'TRACE_INVALID', 'trace')
            _need(event.tool_name in TOOL_LEVELS and event.tool_name in case.allowed_tools, 'TOOL_FORBIDDEN', 'trace')
            start = datetime.fromisoformat(event.started_at.replace('Z', '+00:00'))
            end = datetime.fromisoformat(event.finished_at.replace('Z', '+00:00'))
            _need(start.utcoffset() is not None and start.utcoffset().total_seconds() == 0
                  and end.utcoffset() is not None and end.utcoffset().total_seconds() == 0
                  and start <= end and (previous_end is None or previous_end <= start), 'TRACE_INVALID', 'trace')
            first_start = first_start or start
            _need((end - first_start).total_seconds() <= case.timeout_seconds, 'TRACE_INVALID', 'trace')
            previous_end = end
            if event.result_code in {'DATASET_CHANGED', 'VERSION_CONFLICT'}:
                conflict = event
                continue
            if conflict:
                _need(event.tool_name not in _WRITE_TOOLS, 'DATASET_REREAD_REQUIRED', 'trace')
                # 完整新读取必须清除旧游标/版本约束；成功返回由可信传输记录 code=None。
                if event.tool_name in _READ_TOOLS and event.result_code is None:
                    if conflict.tool_name in _READ_TOOLS:
                        omitted = {'cursor', 'page_token', 'dataset_epoch', 'data_version', 'expected_epoch', 'expected_version'}
                        _need(event.tool_name == conflict.tool_name
                              and _same({k:v for k,v in event.arguments.items() if k not in omitted},
                                        {k:v for k,v in conflict.arguments.items() if k not in omitted}),
                              'DATASET_REREAD_REQUIRED', 'trace')
                    _need(not any(event.arguments.get(k) is not None for k in
                                  ('cursor', 'page_token', 'dataset_epoch', 'data_version', 'expected_epoch', 'expected_version')),
                          'DATASET_REREAD_REQUIRED', 'trace')
                    conflict = None
        _need(not conflict, 'DATASET_REREAD_REQUIRED', 'trace')
    _collect(check, failures)
    return failures
