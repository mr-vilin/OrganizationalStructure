"""独立同步进程，租约隔离与短事务发布。"""
import secrets
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.persistence.models import WorkerLease, SyncJob, EventInbox, SystemSetting, DatasetState, Department, Employee, EmployeeDepartment, PendingFact, ChangeLog, SyncStaging
from app.sync.collector import Candidate
from app.persistence.repositories import SqlSyncJobRepository
from app.capabilities.receipts import ReceiptRepository
from app.sync.publisher import Publisher
from app.sync.settings import ScheduleService


def utcnow(): return datetime.now(timezone.utc).replace(tzinfo=None)


SAFE_SYNC_ERRORS=frozenset({'FEISHU_API_ERROR','FEISHU_UNAVAILABLE','INVALID_PAGINATION','DEPARTMENT_CYCLE','FEISHU_MEMBERSHIP_UNREADABLE','FEISHU_STATUS_UNREADABLE','FEISHU_PARENT_UNREADABLE','FEISHU_TOKEN_MISSING','FEISHU_DETAIL_MISSING','FEISHU_ID_MISMATCH'})


class Worker:
    def __init__(self, sessions, collector, owner=None):
        self.sessions, self.collector = sessions, collector
        self.owner, self.generation = owner or secrets.token_urlsafe(24), None
        self.jobs, self.publisher = SqlSyncJobRepository(sessions), Publisher(sessions)
        self.current_job = None
        self.initial_coverage_verified=bool(getattr(collector,'coverage_verified',False))

    def acquire(self, now):
        with self.sessions.begin() as db:
            lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
            if lease is None:
                # 迁移首次建表会种入单例；若运维清理误删，启动时安全补回而不丢失业务数据。
                db.add(WorkerLease(id=1, generation=0))
                db.flush()
                lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
            if lease is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            if lease.owner and lease.expires_at and lease.expires_at > now and lease.owner != self.owner:
                return False
            lease.owner, lease.generation, lease.expires_at = self.owner, lease.generation+1, now+timedelta(seconds=120)
            self.generation = lease.generation
            return True

    def renew(self, now):
        with self.sessions.begin() as db:
            lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
            if lease.owner != self.owner or lease.generation != self.generation or not lease.expires_at or lease.expires_at <= now:
                return False
            lease.expires_at = now+timedelta(seconds=120)
            if self.current_job:
                job = db.scalar(select(SyncJob).where(SyncJob.id == self.current_job[0]).with_for_update())
                if job and job.status == 'running' and job.lease_generation == self.current_job[1]: job.lease_expires_at = lease.expires_at
            return True

    def recover(self, now):
        with self.sessions.begin() as db:
            lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
            if lease.owner != self.owner or lease.generation != self.generation: raise ValueError('STALE_LEASE')
            for job in db.scalars(select(SyncJob).where(SyncJob.status == 'running', SyncJob.lease_expires_at < now).with_for_update()):
                job.status, job.lease_generation, job.updated_at = 'queued', job.lease_generation+1, now
                job.lease_expires_at = None

    def step(self):
        now = utcnow()
        if not self.renew(now): raise ValueError('STALE_LEASE')
        self.recover(now)
        ScheduleService(self.sessions).due(now)
        job = self.jobs.claim_next(now, now+timedelta(seconds=120))
        if job:
            if job.type == 'reconcile' and not self._initialization_complete():
                with self.sessions.begin() as db:
                    row = db.get(SyncJob, job.id)
                    if row and row.status == 'running':
                        row.status, row.phase, row.lease_expires_at, row.updated_at = 'queued', 'waiting_initialization', None, now
                return False
            self.current_job = (job.id, job.lease_generation)
            try:
                self._refresh_coverage()
                if hasattr(self.collector,'progress'): self.collector.progress=self._progress
                root=job.root_department_id if job.type == 'subtree' else None
                previous_departments,previous_users=self._previous_scope(root)
                candidate = self._staged_candidate(job)
                if candidate is None:
                    candidate = self.collector.collect(root,previous_departments=previous_departments,previous_users=previous_users)
                    self._stage_candidate(job.id, candidate)
                with self.sessions() as db:
                    if db.get(SystemSetting,'coverage_invalidated'): candidate.coverage_status='unknown'
                self.publisher.publish(candidate, job.id, job.lease_generation, owner=self.owner, lease_generation=self.generation)
            except Exception as exc:
                self._fail_job(job, exc)
            finally:
                self.current_job = None
            return True
        with self.sessions() as db:
            event = db.scalar(select(EventInbox).where(EventInbox.status == 'queued').order_by(EventInbox.received_at, EventInbox.event_id).limit(1))
        if event:
            with self.sessions() as db:
                state = db.get(DatasetState, 1)
                if state is None or state.initialization_status != 'complete':
                    return False
            try:
                self._refresh_coverage()
                if event.event_type == 'contact.scope.updated_v3':
                    candidate = self.collector.collect()
                else:
                    candidate = self.collector.event(event.event_type, event.object_id)
                self.publisher.publish(candidate, event_id=event.event_id, owner=self.owner, lease_generation=self.generation)
            except Exception:
                self._fail_event(event.event_id)
            return True
        return False

    def _initialization_complete(self):
        with self.sessions() as db:
            state = db.get(DatasetState, 1)
            return state is not None and state.initialization_status == 'complete'

    def _stage_candidate(self, job_id, candidate):
        """在发布事务前保存规范化候选，供进程中断后的诊断和恢复使用。"""
        from app.persistence.models import SyncStaging
        with self.sessions.begin() as db:
            for kind, records in [('department', candidate.departments), ('employee', candidate.employees)]:
                for identifier, value in records.items():
                    db.merge(SyncStaging(job_id=job_id, object_type=kind, source_id=identifier, normalized_data=value))
            for kind, identifier in candidate.pending:
                db.merge(SyncStaging(job_id=job_id, object_type=kind, source_id=identifier, normalized_data={'pending': True}))

    def _staged_candidate(self, job):
        """恢复已有规范化候选；没有完整检查点时返回 None 触发重新采集。"""
        with self.sessions() as db:
            rows = list(db.scalars(select(SyncStaging).where(SyncStaging.job_id == job.id)))
        if not rows:
            return None
        result = Candidate(full=job.type != 'subtree')
        for row in rows:
            if row.normalized_data == {'pending': True}:
                result.pending.append((row.object_type, row.source_id))
            elif row.object_type == 'department':
                result.departments[row.source_id] = row.normalized_data
            elif row.object_type == 'employee':
                result.employees[row.source_id] = row.normalized_data
        return result

    def _refresh_coverage(self):
        from app.sync.coverage import CoverageService
        if hasattr(self.collector,'coverage_verified'):
            self.collector.coverage_verified=CoverageService(self.sessions).verified(self.initial_coverage_verified)

    def _previous_scope(self,root):
        with self.sessions() as db:
            departments=list(db.scalars(select(Department)))
            if root is None:
                pending=list(db.scalars(select(PendingFact)))
                return {d.id for d in departments}|{p.source_id for p in pending if p.object_type=='department'},set(db.scalars(select(Employee.id)))|{p.source_id for p in pending if p.object_type=='employee'}
            ids={root}
            while True:
                children={d.id for d in departments if d.parent_id in ids}-ids
                if not children: break
                ids.update(children)
            users=set(db.scalars(select(EmployeeDepartment.employee_id).where(EmployeeDepartment.department_id.in_(ids))))
            return ids,users

    def _progress(self,**value):
        now=utcnow()
        with self.sessions.begin() as db:
            lease=db.scalar(select(WorkerLease).where(WorkerLease.id==1).with_for_update())
            if lease.owner!=self.owner or lease.generation!=self.generation or lease.expires_at<=now: raise ValueError('STALE_LEASE')
            if not self.current_job: return
            row=db.scalar(select(SyncJob).where(SyncJob.id==self.current_job[0]).with_for_update())
            if row.status!='running' or row.lease_generation!=self.current_job[1]: raise ValueError('STALE_LEASE')
            row.phase,row.updated_at=value['phase'],now
            db.merge(SystemSetting(key='job_progress:'+row.id,value=json.dumps(value)))

    def _fail_event(self,event_id):
        now=utcnow()
        with self.sessions.begin() as db:
            lease=db.scalar(select(WorkerLease).where(WorkerLease.id==1).with_for_update())
            if not lease or lease.owner!=self.owner or lease.generation!=self.generation or not lease.expires_at or lease.expires_at<=now: return
            row=db.scalar(select(EventInbox).where(EventInbox.event_id==event_id).with_for_update())
            if not row or row.status!='queued': return
            row.attempts+=1
            row.status='failed'
            row.payload={**row.payload,'error_code':'EVENT_PROCESSING_FAILED'}

    def _fail_job(self, claimed, exc):
        now = utcnow()
        with self.sessions.begin() as db:
            lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
            if lease.owner != self.owner or lease.generation != self.generation or lease.expires_at <= now: return
            # 与 Publisher 一致：WorkerLease → DatasetState → job → receipt。
            self.jobs._lock_dataset(db)
            row = db.scalar(select(SyncJob).where(SyncJob.id == claimed.id).with_for_update())
            if row.status != 'running' or row.lease_generation != claimed.lease_generation: return
            row.error_code = str(exc) if str(exc) in SAFE_SYNC_ERRORS else 'SYNC_FAILED'
            row.error_detail = None
            row.phase, row.updated_at = 'collection_failed', now
            row.status = 'queued' if row.attempt < 5 else 'failed'
            if row.status == 'queued':
                row.retry_count = (row.retry_count or 0) + 1
            row.lease_expires_at = now+timedelta(seconds=min(900, 15 * 2 ** row.attempt)) if row.status == 'queued' else None
            row.attempt += 1 if row.status == 'queued' else 0
            db.add(ChangeLog(object_type='sync_job', object_id=row.id, source='worker', actor=self.owner, job_id=row.id, before_data={'status': 'running'}, after_data={'status': row.status, 'error_code': row.error_code, 'attempt': row.attempt}, committed_at=now))
            if row.status == 'failed':
                row.finished_at = now
                ReceiptRepository().finalize_job_in_session(db, row, now)


def main():
    from app.config import get_settings
    from app.dependencies import get_runtime
    from app.feishu.client import FeishuClient
    from app.sync.collector import Collector
    settings, runtime = get_settings(), get_runtime()
    if not runtime or not settings.feishu_app_id or not settings.feishu_app_secret or not settings.feishu_tenant_key:
        raise SystemExit('同步未配置：需要数据库、会话密钥、飞书应用与租户配置')
    from app.feishu.binding import bind_connection
    bind_connection(runtime.sessions,settings.feishu_app_id,settings.feishu_tenant_key)
    verified = bool(settings.coverage_all_members_verified and settings.coverage_departmentless_verified and settings.coverage_acceptance_reference.strip())
    from app.feishu.binding import custom_attrs
    mappings = custom_attrs(runtime.sessions)
    worker = Worker(runtime.sessions, Collector(FeishuClient(settings.feishu_app_id, settings.feishu_app_secret.get_secret_value()), verified, custom_mappings=mappings, employee_type_options=set((mappings.get('employee_type_options') or {}).keys())))
    stop = threading.Event()
    while not worker.acquire(utcnow()): time.sleep(5)
    worker.recover(utcnow())
    def heartbeat():
        while not stop.wait(30):
            try:
                if not worker.renew(utcnow()): stop.set()
            except Exception: stop.set()
    thread=threading.Thread(target=heartbeat, daemon=True); thread.start()
    try:
        while not stop.is_set():
            if not worker.step(): stop.wait(2)
    except KeyboardInterrupt: pass
    finally:
        stop.set(); thread.join(timeout=5)


if __name__ == '__main__': main()
