"""固定脚本 smoke 编排；脚本只拿目标、MCP 与身份，不读取夹具或期望。"""
from .worker import ScriptedWorkerAgent, ToolStep


def _version(results, context):
    observation = results[-1]['observation']
    return observation['dataset_epoch'], observation['data_version']


def _store_steps(department_id, store_code, employee_id, *, conflict=False):
    changes = [{'department_id': department_id, 'is_store': True, 'store_code': store_code}]
    def preview(results, context):
        return {'changes': changes, 'expected_version': _version(results, context)[1]}
    def apply(results, context):
        epoch, version = _version(results, context)
        return {'changes': changes, 'expected_epoch': epoch, 'expected_version': version,
                'idempotency_key': context.run_id + '-store'}
    steps = [ToolStep('get_employee', {'employee_id': employee_id}),
             ToolStep('preview_store_changes', preview), ToolStep('apply_store_changes', apply)]
    if conflict:
        steps.append(ToolStep('get_store', {'store_id': department_id}))
    steps.append(ToolStep('get_employee', {'employee_id': employee_id}))
    return steps


def _sync_steps(job_type, root=None):
    def request(results, context):
        arguments = {'job_type': job_type, 'idempotency_key': context.run_id + '-sync'}
        if root is not None:
            arguments['root_department_id'] = root
        return arguments
    return [ToolStep('request_sync', request),
            ToolStep('get_sync_job', lambda results, context: {'job_id': results[0]['data']['job_id']},
                     until=lambda result: result['data']['status'] in {'succeeded', 'failed'}, max_attempts=50),
            ToolStep('get_employee', {'employee_id': 'eval_user'})]


def _steps(goal, context):
    scripts = {
        'ORG_AGENT_READ_PRIMARY_STORE': lambda: [ToolStep('get_employee', {'employee_id': 'eval_employee_primary'})],
        'ORG_AGENT_READ_NOT_IN_STORE': lambda: [ToolStep('get_employee', {'employee_id': 'eval_employee_hq'})],
        'ORG_AGENT_APPLY_STORE': lambda: _store_steps('people_service', 'EVAL_SERVICE', 'eval_employee_primary'),
        'ORG_AGENT_VERSION_CONFLICT': lambda: _store_steps('store_people', 'EVAL_WORKER', 'eval_employee_primary', conflict=True),
        'ORG_AGENT_SYNC_SUBTREE': lambda: _sync_steps('subtree', 'eval_store'),
        'ORG_AGENT_PERMISSION_SHRINK': lambda: _sync_steps('full'),
    }
    if context.case_id not in scripts:
        raise ValueError('EVALUATION_SCRIPT_REQUIRED')
    return scripts[context.case_id]()


def smoke_worker():
    return ScriptedWorkerAgent(_steps)


def conflict_hook():
    """可信控制面制造一次真实独立写入；不向 Worker 暴露控制方法。"""
    injected = set()
    def after_tool(case, context, harness, name, arguments, result):
        if (case.case_id == 'ORG_AGENT_VERSION_CONFLICT' and context.run_id not in injected
                and name == 'preview_store_changes' and result.get('error') is None):
            harness.change_store_concurrently('store_people', 'EVAL_CONCURRENT',
                                              result['observation']['data_version'])
            injected.add(context.run_id)
    return after_tool
