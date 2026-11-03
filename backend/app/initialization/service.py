"""初始化状态、预检证据和重来清理共用数据集行锁。"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from app.persistence.models import (
    ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore,
    EventInbox, FeishuConnection, PendingFact, StoreCodeReservation, StoreProfile,
    SyncJob, SyncStaging, SystemSetting, WorkerLease,
)
from app.persistence.repositories import SqlSyncJobRepository
from .validation import InitializationFailure, validate_definitions, validate_department, validate_user

FLOW_KEY = 'initialization_flow'
STEP_TITLES = ['检查配置', '测试飞书连接', '试读部门与人员', '核验所需字段']


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def load_flow(db):
    row = db.get(SystemSetting, FLOW_KEY)
    flow = json.loads(row.value) if row else {'flow_id': None, 'phase': 'pending', 'checks': [], 'evidence': None}
    if '_chunks' in flow:
        parts = [db.get(SystemSetting, f'{FLOW_KEY}:chunk:{i}').value for i in range(flow['_chunks'])]
        return json.loads(''.join(parts))
    return flow


def save_flow(db, flow):
    payload = json.dumps(flow, ensure_ascii=False)
    # TEXT 上限为 64 KiB；大型企业全员名单按 Unicode 字符分片，事务内一起切换。
    db.execute(delete(SystemSetting).where(SystemSetting.key.like(FLOW_KEY + ':chunk:%')))
    if len(payload.encode('utf-8')) > 48000:
        parts = [payload[i:i + 12000] for i in range(0, len(payload), 12000)]
        for i, part in enumerate(parts):
            db.add(SystemSetting(key=f'{FLOW_KEY}:chunk:{i}', value=part))
        payload = json.dumps({**{key: flow[key] for key in ('flow_id', 'phase', 'checks')}, '_chunks': len(parts)}, ensure_ascii=False)
    db.merge(SystemSetting(key=FLOW_KEY, value=payload))


def fail_interrupted(db, job, now):
    job.status, job.phase, job.error_code = 'failed', 'interrupted', 'INITIALIZATION_INTERRUPTED'
    job.error_detail = '后台初始化任务已中断，请清理后重新开始'
    job.finished_at, job.updated_at, job.lease_expires_at = now, now, None
    job.lease_generation += 1
    flow = load_flow(db)
    if flow.get('job_id') == job.id:
        flow.update(phase='failed', last_error={'code': job.error_code, 'message': job.error_detail})
        save_flow(db, flow)
    db.add(ChangeLog(object_type='sync_job', object_id=job.id, source='worker', actor='system:lease-expiry',
                     job_id=job.id, before_data={'status': 'running'},
                     after_data={'status': 'failed', 'error_code': job.error_code}, committed_at=now))


def fingerprint(settings, mappings):
    # 只持久化整体摘要，密钥不进入页面、日志或配置快照。
    values = [settings.feishu_app_id, settings.feishu_tenant_key, settings.feishu_redirect_uri,
              settings.feishu_app_secret.get_secret_value() if settings.feishu_app_secret else '', mappings]
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audit(db, action, actor, flow, **details):
    db.add(ChangeLog(object_type='initialization', object_id=flow['flow_id'] or 'initialization',
                     source='admin', actor=actor, job_id=flow.get('job_id'), before_data=None,
                     after_data={'action': action, **details}, committed_at=utcnow()))


def check_item(key, title, passed, message=''):
    return {'key': key, 'title': title, 'status': 'passed' if passed else 'failed', 'message': message}


class InitializationService:
    def __init__(self, sessions, settings, api=None):
        self.sessions, self.settings, self.api = sessions, settings, api

    def _lock(self, db):
        state = SqlSyncJobRepository._lock_dataset(db)
        flow = load_flow(db)
        if not flow.get('flow_id'):
            flow['flow_id'] = uuid.uuid4().hex
        return state, flow

    @staticmethod
    def _editable(state, flow):
        if state.initialization_status == 'complete':
            raise InitializationFailure('INITIALIZATION_ALREADY_COMPLETE', '初始化已经完成')
        if flow['phase'] in ('running', 'failed', 'cleanup_required'):
            raise InitializationFailure('INITIALIZATION_RESTART_REQUIRED', '请查看任务进度，或先清理后重新开始')

    def status(self):
        with self.sessions.begin() as db:
            state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            if state is None:
                raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            flow = load_flow(db)
            job = db.get(SyncJob, flow.get('job_id')) if flow.get('job_id') else None
            if job and job.status == 'running' and (not job.lease_expires_at or job.lease_expires_at <= utcnow()):
                fail_interrupted(db, job, utcnow())
                flow = load_flow(db)
            if job and job.status == 'failed' and flow['phase'] != 'failed':
                flow['phase'] = 'failed'
                flow['last_error'] = {'code': job.error_code, 'message': job.error_detail or '后台初始化任务已中断，请重新开始'}
                save_flow(db, flow)
            if flow['phase'] == 'checking' and flow.get('operation_expires_at', '') < utcnow().isoformat():
                flow['phase'] = 'precheck_failed'
                flow['last_error'] = {'code': 'PRECHECK_INTERRUPTED', 'message': '上次预检未完成，请重新检测'}
                step = flow.get('checking_step', len(flow['checks']) + 1)
                flow['checks'] = flow['checks'][:step - 1] + [{'step': step, 'title': STEP_TITLES[step - 1], 'status': 'failed',
                    'items': [check_item('interrupted', '预检已中断', False, '请重新检测本步骤')]}]
                flow.pop('operation', None)
                save_flow(db, flow)
                audit(db, 'precheck_interrupted', 'system:timeout', flow, step=step)
            if state.initialization_status != 'complete' and flow['phase'] not in ('running', 'failed', 'cleanup_required'):
                if flow.get('config_fingerprint') not in (None, fingerprint(self.settings, custom_attrs_in_session(db))):
                    flow = {'flow_id': uuid.uuid4().hex, 'phase': 'pending', 'checks': [], 'evidence': None}
                    save_flow(db, flow)
                elif len(flow['checks']) >= 2 and db.get(SystemSetting, 'coverage_invalidated'):
                    flow.update(phase='pending', checks=flow['checks'][:1], evidence=None)
                    flow.pop('operation', None)
                    save_flow(db, flow)
            record = db.get(SystemSetting, 'job_progress:' + job.id) if job else None
            result = {k: v for k, v in flow.items() if k not in ('samples', 'definitions', 'config_fingerprint', 'operation')}
            result['complete'] = state.initialization_status == 'complete'
            result['phase'] = 'complete' if result['complete'] else flow['phase']
            result['settings'] = custom_attrs_in_session(db)
            result['job'] = None if not job else {
                'job_id': job.id, 'status': job.status, 'phase': job.phase,
                'started_at': iso(job.started_at), 'updated_at': iso(job.updated_at), 'finished_at': iso(job.finished_at),
                'error_code': job.error_code, 'error_detail': job.error_detail,
                'progress': json.loads(record.value) if record else {},
            }
            return result

    def configure(self, mappings, actor):
        with self.sessions.begin() as db:
            state, flow = self._lock(db)
            self._editable(state, flow)
            connection = db.get(FeishuConnection, 1)
            if connection is None:
                raise InitializationFailure('CONFIG_BINDING_MISSING', '请先完成飞书应用与企业绑定')
            if set(mappings) - {'permission_role', 'store_attribute', 'employee_type_options'}:
                raise InitializationFailure('VALIDATION_ERROR', '存在不支持的设置')
            if any(not isinstance(mappings.get(k), str) or not mappings[k].strip() for k in ('permission_role', 'store_attribute')):
                raise InitializationFailure('VALIDATION_ERROR', '请填写两个自定义字段的 ID')
            options = mappings.get('employee_type_options')
            if not isinstance(options, dict) or any(not k or not isinstance(v, str) or not v.strip() for k, v in options.items()):
                raise InitializationFailure('VALIDATION_ERROR', '员工类型选项必须是标识与名称的对应表')
            connection.custom_attrs = mappings
            flow = {'flow_id': flow['flow_id'], 'phase': 'pending', 'checks': [], 'evidence': None}
            save_flow(db, flow)
            audit(db, 'configure', actor, flow, mappings=mappings)
        return self.status()

    def run_check(self, step, actor):
        operation = uuid.uuid4().hex
        with self.sessions.begin() as db:
            state, flow = self._lock(db)
            self._editable(state, flow)
            if flow['phase'] == 'checking' and flow.get('operation_expires_at', '') > utcnow().isoformat():
                raise InitializationFailure('INITIALIZATION_BUSY', '另一位管理员正在检测，请稍后查看结果')
            current_fingerprint = fingerprint(self.settings, custom_attrs_in_session(db))
            if flow.get('config_fingerprint') not in (None, current_fingerprint):
                flow.update(checks=[], evidence=None)
            if len(flow['checks']) < step - 1 or any(c['status'] != 'passed' for c in flow['checks'][:step - 1]):
                raise InitializationFailure('PREFLIGHT_REQUIRED', '请从第一步依次完成检查')
            if step == 2 and db.get(SystemSetting, 'coverage_invalidated'):
                db.execute(delete(SystemSetting).where(SystemSetting.key == 'coverage_invalidated'))
                flow['evidence'] = None
            flow.update(phase='checking', checking_step=step, operation=operation,
                        operation_expires_at=(utcnow() + timedelta(minutes=5)).isoformat(),
                        config_fingerprint=current_fingerprint, checks=flow['checks'][:step - 1])
            flow.pop('last_error', None)
            save_flow(db, flow)
            snapshot = dict(flow)
            mappings = custom_attrs_in_session(db)
        try:
            items, extra = self._perform(step, snapshot, mappings)
            failure = None
        except InitializationFailure as exc:
            items, extra = [check_item('error', STEP_TITLES[step - 1], False, exc.message)], {}
            failure = {'code': exc.code, 'message': exc.message, 'issues': exc.issues}
        except Exception:
            items, extra = [check_item('remote', STEP_TITLES[step - 1], False, '飞书请求失败，请检查网络、应用权限及配置后重新检测')], {}
            failure = {'code': 'INITIALIZATION_CHECK_FAILED', 'message': items[0]['message']}
        with self.sessions.begin() as db:
            state, flow = self._lock(db)
            if flow.get('operation') != operation or fingerprint(self.settings, custom_attrs_in_session(db)) != current_fingerprint:
                raise InitializationFailure('PREFLIGHT_STALE', '配置或流程已变化，请重新检测')
            passed = all(item['status'] == 'passed' for item in items)
            flow.update(extra)
            flow['checks'].append({'step': step, 'title': STEP_TITLES[step - 1], 'status': 'passed' if passed else 'failed',
                                   'items': items, 'checked_at': utcnow().isoformat()})
            flow['phase'] = 'ready' if passed and step == 4 else 'pending' if passed else 'precheck_failed'
            flow.pop('operation', None)
            if failure:
                flow['last_error'] = failure
            save_flow(db, flow)
            audit(db, 'precheck', actor, flow, step=step, passed=passed, error=failure)
        return self.status()

    def _perform(self, step, flow, mappings):
        if step == 1:
            with self.sessions() as db:
                connection = db.get(FeishuConnection, 1)
                bound = connection is not None and connection.app_id == self.settings.feishu_app_id and connection.tenant_key == self.settings.feishu_tenant_key
                storage = db.get(SystemSetting, 'task_queue_lock') is not None and db.get(WorkerLease, 1) is not None
            configured = all(isinstance(mappings.get(k), str) and mappings[k].strip() for k in ('permission_role', 'store_attribute')) and isinstance(mappings.get('employee_type_options'), dict)
            return [check_item('storage', '存储与任务单例', storage, '' if storage else '请执行当前版本数据库迁移'),
                    check_item('identity', '飞书应用、租户及登录配置', self.settings.identity_ready and bound, '' if self.settings.identity_ready and bound else '请在部署配置中核对应用、密钥和企业绑定'),
                    check_item('mappings', '自定义字段与员工类型映射', configured, '' if configured else '请在本页配置非敏感字段映射')], {}
        if step == 2:
            next(self.api.pages('users', department_id='0'))
            next(self.api.pages('scopes'))
            return [check_item('connection', '飞书实际请求', True), check_item('whole_enterprise', '根部门全员通讯录授权', True)], {}
        if step == 3:
            children = next(self.api.pages('children', department_id='0')).get('items', [])[:3]
            scope = next(self.api.pages('scopes'))
            user_ids = set(scope.get('user_ids', [])[:3])
            for identifier in ['0', *[item['open_department_id'] for item in children]]:
                user_ids.update(item['user_id'] for item in next(self.api.pages('users', department_id=identifier)).get('items', [])[:3])
            users = [self.api.detail('user', i) for i in sorted(user_ids)[:3]]
            departments = [self.api.detail('department', item['open_department_id']) for item in children]
            return [check_item('departments', '部门结构试读', True, f'已读取 {len(departments)} 个部门样本；无子部门时核验根结构'),
                    check_item('employees', '人员详情试读', bool(users), f'已读取 {len(users)} 个人员样本' if users else '没有可读取的人员样本，请检查权限')], {'samples': {'users': users, 'departments': departments}}
        definitions = validate_definitions(list(item for page in self.api.pages('custom_attrs') for item in page.get('items', [])), mappings)
        items = [check_item('custom_definitions', '自定义字段定义及选项', True)]
        samples = flow.get('samples') or {}
        for raw in samples.get('departments', []):
            validate_department(raw)
        for raw in samples.get('users', []):
            validate_user(raw, mappings, definitions)
        for key, title in [('core', '核心标识、名称与状态'), ('relations', '部门关系和唯一主部门'),
                           ('optional', '工号、职务、上级与员工类型'), ('custom_values', '权限角色与门店属性值')]:
            items.append(check_item(key, title, True))
        return items, {'definitions': definitions}

    def start(self, actor):
        with self.sessions.begin() as db:
            state, flow = self._lock(db)
            if flow['phase'] == 'running':
                current = db.get(SyncJob, flow.get('job_id'))
                if current and current.status in ('queued', 'running'):
                    return flow['job_id']
                raise InitializationFailure('INITIALIZATION_RESTART_REQUIRED', '本轮已结束，请清理后重新开始')
            self._editable(state, flow)
            if (flow['phase'] != 'ready' or len(flow['checks']) != 4
                    or any(c['status'] != 'passed' for c in flow['checks'])
                    or flow.get('config_fingerprint') != fingerprint(self.settings, custom_attrs_in_session(db))
                    or db.get(SystemSetting, 'coverage_invalidated')):
                raise InitializationFailure('PREFLIGHT_REQUIRED', '所有预检通过后才能开始同步')
            job, _ = SqlSyncJobRepository(self.sessions).submit_in_session(
                db, 'initialize', None, actor, utcnow(), '全屏向导初始化', initialization_flow=flow['flow_id'])
            flow.update(phase='running', job_id=job.id)
            save_flow(db, flow)
            audit(db, 'start', actor, flow)
            return job.id

    def restart(self, actor):
        with self.sessions.begin() as db:
            # 与 worker/publisher 一致的锁顺序；清理和流程切换在一个事务内提交。
            lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
            state, flow = self._lock(db)
            if state.initialization_status == 'complete':
                raise InitializationFailure('INITIALIZATION_ALREADY_COMPLETE', '初始化已经完成')
            job = db.get(SyncJob, flow.get('job_id')) if flow.get('job_id') else None
            if job and (job.status == 'queued' or (job.status == 'running' and job.lease_expires_at and job.lease_expires_at > utcnow())):
                raise InitializationFailure('INITIALIZATION_BUSY', '后台同步仍在运行，请查看进度')
            if flow['phase'] not in ('failed', 'cleanup_required', 'running'):
                raise InitializationFailure('INITIALIZATION_RESTART_NOT_REQUIRED', '当前不需要清理，修正后重新检测即可')
            # 不终止仍健康的空闲 worker；任务自身的世代号和数据集世代隔离旧执行。
            for old in db.scalars(select(SyncJob).where(SyncJob.status.in_(('queued', 'running'))).with_for_update()):
                old.status, old.phase, old.error_code = 'failed', 'superseded', 'INITIALIZATION_RESTARTED'
                old.finished_at, old.updated_at, old.lease_expires_at = utcnow(), utcnow(), None
                old.lease_generation += 1
            db.execute(update(EventInbox).where(EventInbox.status == 'queued').values(status='superseded'))
            for model in (SyncStaging, PendingFact, EmployeeStore, EmployeeDepartment, StoreCodeReservation, StoreProfile):
                db.execute(delete(model))
            db.execute(update(Employee).values(primary_department_id=None))
            db.execute(delete(Employee))
            db.execute(update(Department).values(parent_id=None))
            db.execute(delete(Department))
            db.execute(delete(SystemSetting).where(SystemSetting.key.like('job_progress:%')))
            db.execute(delete(SystemSetting).where(SystemSetting.key.in_(('coverage_acceptance', 'coverage_invalidated', 'last_event_processed_at'))))
            state.dataset_epoch, state.data_version = uuid.uuid4().hex, 0
            state.initialization_status, state.coverage_status, state.last_full_sync_at = 'pending', 'unknown', None
            audit(db, 'cleanup', actor, flow, previous_error=flow.get('last_error'))
            fresh = {'flow_id': uuid.uuid4().hex, 'phase': 'pending', 'checks': [], 'evidence': None}
            save_flow(db, fresh)
        return self.status()

    def execution_context(self, job_id):
        with self.sessions() as db:
            state, flow = db.get(DatasetState, 1), load_flow(db)
            if (state.initialization_status == 'complete' or flow.get('job_id') != job_id or flow['phase'] != 'running'
                    or flow.get('config_fingerprint') != fingerprint(self.settings, custom_attrs_in_session(db))
                    or db.get(SystemSetting, 'coverage_invalidated')):
                raise InitializationFailure('PREFLIGHT_STALE', '配置、授权或初始化流程已变化，请重新开始')
            return flow, custom_attrs_in_session(db)


def custom_attrs_in_session(db):
    connection = db.get(FeishuConnection, 1)
    return dict(connection.custom_attrs or {}) if connection else {}


def iso(value):
    return value.isoformat() + 'Z' if value else None
