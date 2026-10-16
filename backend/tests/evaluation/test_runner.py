from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import time
import pytest

from app.evaluation.cases import load_case
from app.evaluation.evidence import DatabaseSnapshot, BUSINESS_TABLES
from app.evaluation.models import AgentRun
from app.evaluation.runner import EvaluationRunner
from app.evaluation.worker import ScriptedWorkerAgent, ToolStep
from app.evaluation.report import report_json, report_markdown

CASE = Path(__file__).parent / 'cases/org_agent_read_primary_store.yaml'

class HarnessDouble:
    def __init__(self, case, context):
        self.case, self.context = case, context
        self.log = []
        self.sensitive_values = ('private-canary-value',)
        self.quiet = True
    def open(self): self.log += ['reset', 'seed', 'start']
    def snapshot(self):
        self.log.append('snapshot')
        tables = {name: [] for name in BUSINESS_TABLES}
        tables['dataset_state'] = [self.case.fixture['dataset_state']]
        tables['employee'] = self.case.fixture['employees']
        tables['employee_department'] = self.case.fixture['employee_departments']
        tables['employee_store'] = self.case.fixture['employee_stores']
        return DatabaseSnapshot(tables)
    def call_tool(self, name, arguments):
        self.log.append(name)
        return SimpleNamespace(is_error=False, structured_content={
            'operation_id': None, 'error': None, 'audit': {},
            'data': {'data': dict(id='eval_employee_primary', **{k: self.case.expected_state[k] for k in
                ('primary_department_id','primary_store_id','primary_store_status','store_ids')}),
                'meta': {'dataset_epoch':'test-eval-primary-store','data_version':1}},
            'observation': {'execution':'submitted','fact_quality':'resolved',
                'dataset_epoch':'test-eval-primary-store','data_version':1}})
    def quiesce(self, timeout): self.log.append('quiet'); return self.quiet
    def fake_writes(self): return {'count':0,'by_method':{}}
    def close(self): self.log += ['release', 'reset_final']


def runner(worker=None):
    instances = []
    def factory(case, context):
        instance = HarnessDouble(case, context); instances.append(instance); return instance
    return EvaluationRunner(worker or ScriptedWorkerAgent([ToolStep('get_employee', {'employee_id':'eval_employee_primary'})]),
                            harness_factory=factory, shutdown_timeout=.1), instances


def test_unique_runs_and_lifecycle():
    run, instances = runner()
    reports = [run.run_case(load_case(CASE)) for _ in range(2)]
    assert all(report.hard_passed for report in reports)
    assert reports[0].run_id != reports[1].run_id
    assert all(report.run_id.startswith('test-') for report in reports)
    assert instances[0].log == ['reset','seed','start','snapshot','get_employee','quiet','snapshot','release','reset_final']
    assert reports[0].evidence['mcp_response_count'] == 1


def test_forged_worker_trace_cannot_complete_read():
    run, instances = runner(SimpleNamespace(run=lambda *args: AgentRun('done', (), {})))
    report = run.run_case(load_case(CASE))
    assert not report.hard_passed and 'MISSING_EVIDENCE' in report.hard_failures
    assert instances[0].log[-2:] == ['release','reset_final']


@pytest.mark.parametrize('steps,code', [
    ([ToolStep('get_system_status', {})], 'TOOL_FORBIDDEN'),
    ([ToolStep('get_employee', {'employee_id':'eval_employee_primary'})]*2, 'TOOL_BUDGET_EXCEEDED')])
def test_wrapper_enforces_policy_before_dispatch(steps, code):
    run, instances = runner(ScriptedWorkerAgent(steps))
    report = run.run_case(replace(load_case(CASE), max_tool_calls=1))
    assert code in report.hard_failures
    assert instances[0].log.count('get_employee') <= 1
    assert 'get_system_status' not in instances[0].log


def test_exception_is_safe_and_always_cleans():
    def fail(*args): raise RuntimeError('private-canary-value')
    run, instances = runner(SimpleNamespace(run=fail))
    report = run.run_case(load_case(CASE))
    assert 'WORKER_FAILED' in report.hard_failures
    assert instances[0].log[-1] == 'reset_final'
    assert 'private-canary-value' not in report_json(report) + report_markdown(report)


def test_unquiet_blocks_next_case_and_recover_is_explicit():
    run, instances = runner()
    original = run.harness_factory
    def factory(case, context):
        h = original(case, context); h.quiet=False; return h
    run.harness_factory = factory
    reports = run.run_suite([load_case(CASE), load_case(CASE)])
    assert len(reports) == 1 and 'SYSTEM_NOT_QUIET' in reports[0].hard_failures
    assert 'reset_final' not in instances[0].log
    with pytest.raises(RuntimeError, match='EVALUATION_RECOVERY_REQUIRED'):
        run.run_case(load_case(CASE))
    instances[0].quiet=True
    assert run.recover()
    assert instances[0].log[-1] == 'reset_final'

@pytest.mark.parametrize('filename', ['org_agent_read_primary_store.yaml', 'org_agent_read_not_in_store.yaml'])
def test_real_mysql_official_mcp_vertical(filename):
    import os
    from sqlalchemy import select, func
    from app.persistence.database import create_mysql_engine
    from app.persistence.models import Base, DatasetState, WorkerLease
    url = os.getenv('ORG_TEST_DATABASE_URL')
    if not url: pytest.skip('需要显式测试 MySQL')
    case = load_case(CASE.parent / filename)
    run = EvaluationRunner(database_url=url)
    report = run.run_case(case)
    assert report.hard_passed, report.hard_failures
    assert report.evidence['mcp_response_count'] == 1
    assert report.trace[0].tool_name == 'get_employee'
    assert report.trace[0].arguments == {}
    engine = create_mysql_engine(url)
    try:
        with engine.connect() as connection:
            expected = {'dataset_state':1,'system_setting':2,'worker_lease':1,'feishu_connection':1}
            for table in Base.metadata.tables.values():
                assert connection.scalar(select(func.count()).select_from(table)) == expected.get(table.name,0)
            assert connection.execute(select(DatasetState.dataset_epoch, DatasetState.data_version)).one() == ('pending',0)
            assert connection.scalar(select(WorkerLease.owner)) is None
    finally:
        engine.dispose()


def test_timeout_revokes_late_calls_without_claiming_thread_cancelled():
    import threading
    release, finished = threading.Event(), threading.Event()
    def slow(goal, client, context):
        try:
            release.wait(3)
            client.call_tool('get_employee', {'employee_id':'eval_employee_primary'})
        finally:
            finished.set()
    run, instances = runner(SimpleNamespace(run=slow))
    try:
        started=time.monotonic()
        report=run.run_case(replace(load_case(CASE),timeout_seconds=1))
        assert time.monotonic()-started < 1.8
        assert 'WORKER_TIMEOUT' in report.hard_failures
        assert report.evidence['execution'] == 'unconfirmed'
        assert instances[0].log[-1] == 'reset_final'
    finally:
        release.set()
        assert finished.wait(2)
    assert 'get_employee' not in instances[0].log


def test_inflight_call_is_retained_then_recovered_without_future_cancel():
    import threading
    release, started = threading.Event(), threading.Event()
    run, instances = runner()
    original=run.harness_factory
    def factory(case, context):
        h=original(case,context)
        call=h.call_tool
        def blocked(name,args):
            started.set(); release.wait(5); return call(name,args)
        h.call_tool=blocked
        return h
    run.harness_factory=factory
    try:
        report=run.run_case(replace(load_case(CASE),timeout_seconds=1))
        assert started.is_set()
        assert {'WORKER_TIMEOUT','SYSTEM_NOT_QUIET'} <= set(report.hard_failures)
        assert instances[0].log.count('snapshot') == 1
        assert 'reset_final' not in instances[0].log
        assert not run.recover()
    finally:
        release.set()
        limit=time.monotonic()+2
        while not run.recover() and time.monotonic()<limit: time.sleep(.01)
    assert instances[0].log[-1]=='reset_final'


@pytest.mark.parametrize('location',['response','text','claimed_trace','arguments'])
def test_raw_secret_is_detected_before_public_redaction(location):
    from app.evaluation.models import ToolTraceEvent
    run, instances=runner()
    original=run.harness_factory
    def factory(case,context):
        h=original(case,context)
        call=h.call_tool
        def response(name,args):
            result=call(name,args)
            if location=='response': result.structured_content['data']['private_note']='private-canary-value'
            return result
        h.call_tool=response
        return h
    run.harness_factory=factory
    def worker(goal,client,context):
        args={'employee_id':'eval_employee_primary'}
        if location=='arguments': args['notes']='private-canary-value'
        client.call_tool('get_employee',args)
        fake_trace=() if location!='claimed_trace' else (ToolTraceEvent(1,'get_employee',{'notes':'private-canary-value'},None,None,'',''),)
        return AgentRun('private-canary-value' if location=='text' else 'done',fake_trace,{})
    run.worker=SimpleNamespace(run=worker)
    report=run.run_case(load_case(CASE))
    assert 'SENSITIVE_LEAK' in report.hard_failures
    assert report.evidence['sensitive_leak'] is True
    output=report_json(report)+report_markdown(report)
    assert 'private-canary-value' not in output
    assert '_employees' not in output and '_run' not in output


def test_real_trace_overrides_worker_fabrication_and_remains_detached():
    run, _=runner()
    def worker(goal,client,context):
        data=client.call_tool('get_employee',{'employee_id':'eval_employee_primary'})
        data['data']['data']['store_ids']=[]
        return AgentRun('done',(),{})
    run.worker=SimpleNamespace(run=worker)
    report=run.run_case(load_case(CASE))
    assert report.hard_passed
    assert len(report.trace)==1


def test_assertions_all_execute_when_first_group_fails():
    run, _=runner(SimpleNamespace(run=lambda *args: AgentRun('',(),{})))
    case=replace(load_case(CASE),expected_state={'unsupported':True},forbidden_effects=({'predicate':'unsupported'},))
    report=run.run_case(case)
    assert not report.hard_passed
    assert 'UNSUPPORTED_PREDICATE' in report.hard_failures


def test_provider_is_explicit_and_receives_only_restricted_inputs(monkeypatch):
    from app.evaluation.worker import ProviderWorkerAgent
    seen={}
    class Provider:
        def run(self,**values):
            seen.update(values)
            values['mcp_client'].call_tool('get_employee',{'employee_id':'eval_employee_primary'})
            return AgentRun('done',(),{})
    monkeypatch.setenv('ORG_EVALUATION_MODEL_ALIAS','local-stub')
    monkeypatch.setenv('ORG_EVALUATION_MAX_TOKENS','100')
    run,_=runner(ProviderWorkerAgent(Provider()))
    assert run.run_case(load_case(CASE)).hard_passed
    assert set(seen)=={'goal','mcp_client','context','model_alias','max_tokens'}
    assert not hasattr(seen['mcp_client'],'harness')
    assert seen['model_alias']=='local-stub' and seen['max_tokens']==100


def test_json_chinese_markdown_and_score_validation(tmp_path):
    import json
    from app.evaluation.report import write_report
    run,_=runner()
    report=run.run_case(load_case(CASE))
    json_path,md_path=write_report(report,tmp_path)
    assert json.loads(json_path.read_text(encoding='utf-8'))['hard_passed'] is True
    assert '硬门槛：通过' in md_path.read_text(encoding='utf-8')
    for value in (-.1,1.1,float('nan'),True,'good'):
        with pytest.raises(ValueError): report_json(replace(report,soft_scores={'diagnostic':value}))


def test_cleanup_failure_does_not_hide_original_failure():
    def fail(*args): raise RuntimeError('private-canary-value')
    run,instances=runner(SimpleNamespace(run=fail))
    original=run.harness_factory
    def factory(case,context):
        h=original(case,context)
        h.close=lambda: (_ for _ in ()).throw(RuntimeError('private-canary-value'))
        return h
    run.harness_factory=factory
    report=run.run_case(load_case(CASE))
    assert {'WORKER_FAILED','CLEANUP_FAILED'} <= set(report.hard_failures)
    instances[0].close=lambda: None
    assert run.recover()


def test_real_mysql_production_sync_and_sdk_polling():
    import os
    from copy import deepcopy
    from app.evaluation.harness import SystemHarness
    url=os.getenv('ORG_TEST_DATABASE_URL')
    if not url: pytest.skip('需要显式测试 MySQL')
    fixture=deepcopy(load_case(CASE).fixture)
    for section in ('departments','employees','employee_departments','employee_stores','store_profiles'):
        fixture[section]=[]
    fixture['fake_feishu']={'scenario_id':'baseline'}
    # 可信测试覆盖验收记录，Collector 按生产 CoverageService 读取，不伪造完成。
    fixture['system_settings'].append({'key':'coverage_acceptance','value':
        '{"reference":"synthetic-acceptance","all_members_verified":true,"departmentless_verified":true,"updated_at":"2026-01-01T00:00:00+00:00"}'})
    case=replace(load_case(CASE), case_id='HARNESS_SYNC_SMOKE', fixture=fixture,
        allowed_tools=('request_sync','get_sync_job','get_employee'),max_tool_calls=40,
        expected_state={'employee_id':'eval_user','primary_department_id':'eval_team',
            'primary_store_id':None,'primary_store_status':'not_in_store','store_ids':[],
            'read_completion':{'predicate':'employee_attribution'},'version_delta':1,
            'execution':'submitted','fact_quality':'resolved',
            'operation':{'capability':'request_sync','status':'submitted','count':1,'audit_required':True,'job_required':True},
            'rows':[{'table':'sync_job','where':{'type':'full'},'equals':{'status':'succeeded','failure_count':0},'count':1}]},
        forbidden_effects=({'predicate':'no_feishu_writes'},))
    steps=[ToolStep('request_sync',lambda results,context:{'job_type':'full','idempotency_key':context.run_id}),
        ToolStep('get_sync_job',lambda results,context:{'job_id':results[0]['data']['job_id']},
            until=lambda body:body['data']['status'] in ('succeeded','failed'),max_attempts=30),
        ToolStep('get_employee',{'employee_id':'eval_user'})]
    instances=[]
    def factory(case,context):
        h=SystemHarness(url,case,context); instances.append(h); return h
    run=EvaluationRunner(ScriptedWorkerAgent(steps),harness_factory=factory)
    try:
        report=run.run_case(case)
        assert report.hard_passed, report.hard_failures
        assert instances[0].fake.read_count>0
        assert report.evidence['after']['row_counts']['sync_job']==1
        assert report.evidence['after']['row_counts']['operation_receipt']==1
        assert report.evidence['after']['row_counts']['change_log']>0
    finally:
        assert run.recover()


def test_real_mysql_preview_confirmation_apply_and_final_read():
    import os
    url=os.getenv('ORG_TEST_DATABASE_URL')
    if not url: pytest.skip('需要显式测试 MySQL')
    original=load_case(CASE)
    expected=dict(original.expected_state,version_delta=1,execution='submitted',fact_quality='resolved',
        operation={'capability':'apply_store_changes','status':'submitted','count':1,'audit_required':True,'job_required':False},
        rows=[{'table':'store_profile','where':{'department_id':'store_people'},'equals':{'store_code':'EVAL_CHANGED'},'count':1}])
    case=replace(original,case_id='HARNESS_APPLY_SMOKE',allowed_tools=original.allowed_tools+('preview_store_changes','apply_store_changes'),
        expected_state=expected,forbidden_effects=({'predicate':'no_feishu_writes'},{'predicate':'no_new_sync_jobs'}))
    changes=[{'department_id':'store_people','is_store':True,'store_code':'EVAL_CHANGED'}]
    steps=[ToolStep('get_employee',{'employee_id':'eval_employee_primary'}),
        ToolStep('preview_store_changes',{'changes':changes,'expected_version':1}),
        ToolStep('apply_store_changes',lambda results,context:{'changes':changes,'expected_epoch':'test-eval-primary-store',
            'expected_version':1,'idempotency_key':context.run_id}),
        ToolStep('get_employee',{'employee_id':'eval_employee_primary'})]
    run=EvaluationRunner(ScriptedWorkerAgent(steps),database_url=url)
    try:
        report=run.run_case(case)
        assert report.hard_passed,report.hard_failures
        assert len(report.trace)==4
        assert report.trace[2].operation_id.startswith('op_')
    finally:
        assert run.recover()


@pytest.mark.parametrize('mismatch',[None,'owner','generation'])
def test_real_mysql_expired_lease_release_requires_owned_generation(mismatch):
    import os
    from datetime import timedelta
    from app.evaluation.harness import SystemHarness
    from app.evaluation.models import AgentRunContext
    from app.persistence.models import WorkerLease
    from app.sync.worker import utcnow
    url=os.getenv('ORG_TEST_DATABASE_URL')
    if not url: pytest.skip('需要显式测试 MySQL')
    case=load_case(CASE)
    h=SystemHarness(url,case,AgentRunContext('test-lease-lifecycle',case.case_id,'evaluation-ci','test'))
    h.open()
    try:
        assert h.quiesce(2)
        with h._sessions.begin() as db:
            lease=db.get(WorkerLease,1)
            lease.expires_at=utcnow()-timedelta(seconds=1)
            if mismatch=='owner': lease.owner='another-worker'
            if mismatch=='generation': lease.generation+=1
        if mismatch:
            with pytest.raises(RuntimeError,match='EVALUATION_LEASE_OWNER_CHANGED'): h.close()
            with h._sessions.begin() as db:
                lease=db.get(WorkerLease,1)
                assert lease.owner is not None
                lease.owner=h._worker.owner
                lease.generation=h._worker.generation
        h.close()
        assert h._closed
    finally:
        h.close()


def test_open_failure_is_cleaned_and_no_worker_started():
    run,instances=runner()
    original=run.harness_factory
    def factory(case,context):
        h=original(case,context)
        def fail(): h.log.append('seed_failed'); raise RuntimeError('private-canary-value')
        h.open=fail
        return h
    run.harness_factory=factory
    report=run.run_case(load_case(CASE))
    assert report.hard_failures==('HARNESS_FAILED',)
    assert instances[0].log==['seed_failed','quiet','release','reset_final']


def test_system_quiesces_before_independent_after_snapshot_and_release():
    run,instances=runner()
    report=run.run_case(load_case(CASE))
    log=instances[0].log
    assert report.hard_passed
    assert log.index('quiet')<len(log)-1-log[::-1].index('snapshot')<log.index('release')<log.index('reset_final')


def test_after_tool_hook_runs_inside_trusted_boundary_and_failure_is_hard():
    seen = []
    run, instances = runner()
    run.after_tool = lambda case, context, harness, name, arguments, result: seen.append(
        (case.case_id, context.run_id.startswith('test-'), name, arguments, isinstance(result, dict)))
    report = run.run_case(load_case(CASE))
    assert report.hard_passed
    assert seen == [('ORG_AGENT_READ_PRIMARY_STORE', True, 'get_employee',
                     {'employee_id': 'eval_employee_primary'}, True)]

    def fail_hook(*args):
        raise RuntimeError('private-canary-value')
    run.after_tool = fail_hook
    report = run.run_case(load_case(CASE))
    assert 'HARNESS_HOOK_FAILED' in report.hard_failures
    assert instances[-1].log[-1] == 'reset_final'


@pytest.mark.parametrize('failure', ['transport', 'invalid', 'empty_envelope', 'hook', 'hook_rejection', 'UPSTREAM_TIMEOUT',
                                   'UPSTREAM_UNAVAILABLE', 'UPSTREAM_INVALID_RESPONSE'])
def test_call_failure_revokes_client_even_when_worker_catches_rejection(failure):
    from app.evaluation.runner import CallRejected
    def worker(goal, client, context):
        for _ in range(2):
            try:
                client.call_tool('get_employee', {'employee_id': 'eval_employee_primary'})
            except CallRejected:
                pass
        return AgentRun('done', (), {})
    run, instances = runner(SimpleNamespace(run=worker))
    original = run.harness_factory
    def factory(case, context):
        harness = original(case, context)
        call = harness.call_tool
        def broken(name, arguments):
            result = call(name, arguments)
            if failure == 'transport':
                raise RuntimeError('private-canary-value')
            if failure == 'invalid':
                result.structured_content = None
            elif failure == 'empty_envelope':
                result.structured_content = {}
            elif failure.startswith('UPSTREAM_'):
                result.is_error = True
                result.structured_content['error'] = {'code': failure}
            return result
        harness.call_tool = broken
        return harness
    run.harness_factory = factory
    if failure == 'hook':
        run.after_tool = lambda *args: (_ for _ in ()).throw(RuntimeError('private-canary-value'))
    if failure == 'hook_rejection':
        run.after_tool = lambda *args: (_ for _ in ()).throw(CallRejected('HARNESS_HOOK_FAILED'))
    report = run.run_case(load_case(CASE))
    assert not report.hard_passed
    assert 'CLIENT_REVOKED' in report.hard_failures
    assert instances[0].log.count('get_employee') == 1
