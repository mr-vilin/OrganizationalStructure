import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import delete, select
from app.persistence.models import DatasetState, Department, Employee, EmployeeDepartment, SyncJob, SyncStaging, ChangeLog, EventInbox, SystemSetting, WorkerLease, PendingFact, LoginIdentity, AdminSession
from app.stores.service import StoreAdminService


class Publisher:
    def __init__(self, sessions): self.sessions = sessions

    def publish(self, candidate, job_id=None, generation=None, event_id=None, owner=None, lease_generation=None):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            if owner:
                lease = db.scalar(select(WorkerLease).where(WorkerLease.id == 1).with_for_update())
                if not lease or lease.owner != owner or lease.generation != lease_generation or not lease.expires_at or lease.expires_at <= now:
                    raise ValueError('STALE_LEASE')
            state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
            if state is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update()) if job_id else None
            if job_id and (not job or job.status != 'running' or job.lease_generation != generation or not job.lease_expires_at or job.lease_expires_at <= now):
                raise ValueError('STALE_LEASE')
            candidate=self._defer_unresolved(db,candidate,now)
            if job:
                db.execute(delete(SyncStaging).where(SyncStaging.job_id == job_id))
                for kind, records in [('department', candidate.departments), ('employee', candidate.employees)]:
                    for identifier, value in records.items():
                        db.add(SyncStaging(job_id=job_id, object_type=kind, source_id=identifier, normalized_data=value))
            changes = 0
            # 未解析事实只保存在 pending_fact；已有事实仅降质量。
            for kind, identifier in candidate.pending:
                model = Department if kind == 'department' else Employee
                row = db.get(model, identifier)
                if row is not None and row.sync_quality != 'pending_verification':
                    self._log(db, kind, identifier, {'sync_quality': row.sync_quality}, {'sync_quality': 'pending_verification'}, job_id, now)
                    row.sync_quality = 'pending_verification'; changes += 1
            remaining = dict(candidate.departments)
            while remaining:
                ready = [key for key, value in remaining.items() if not value['parent_id'] or value['parent_id'] not in remaining]
                if not ready: raise RuntimeError('DEPARTMENT_CYCLE')
                for key in ready:
                    value=remaining.pop(key)
                    if value.get('lifecycle_only'):
                        changes+=self._upsert(db,Department,{'id':key,'status':'inactive','sync_quality':'pending_verification'},'department',job_id,now)
                    else:
                        changes += self._upsert(db, Department, value, 'department', job_id, now)
                    if value['status']=='inactive':changes+=self._end_department_memberships(db,key,job_id,now)
                db.flush()
            parents={row.id:row.parent_id for row in db.scalars(select(Department))}
            for identifier in parents:
                visited=set()
                current=identifier
                while current is not None:
                    if current in visited: raise RuntimeError('DEPARTMENT_CYCLE')
                    visited.add(current)
                    current=parents.get(current)
            for key, value in candidate.employees.items():
                if value.get('lifecycle_only'):
                    changes+=self._publish_inactive_lifecycle(db,value,job_id,now)
                    continue
                fields = {k: v for k, v in value.items() if k != 'department_ids'}
                changes += self._upsert(db, Employee, fields, 'employee', job_id, now)
                db.flush()
                if value['status']=='inactive': self._revoke_employee_sessions(db,value['feishu_user_id'],job_id,now)
                before = {(r.department_id, r.is_primary, r.active) for r in db.scalars(select(EmployeeDepartment).where(EmployeeDepartment.employee_id == key))}
                after = {(d, d == value['primary_department_id'], value['status'] == 'active' and db.get(Department,d).status=='active') for d in value['department_ids']}
                if before != after:
                    db.execute(delete(EmployeeDepartment).where(EmployeeDepartment.employee_id == key))
                    for department, primary, active in after:
                        db.add(EmployeeDepartment(employee_id=key, department_id=department, is_primary=primary, active=active))
                    self._log(db, 'membership', key, {'relations': sorted(before)}, {'relations': sorted(after)}, job_id, now)
                    changes += 1
            if candidate.full:
                # 缺席只降质量，保留状态、姓名与所有关系。
                for model, records, kind in [(Department, candidate.departments, 'department'), (Employee, candidate.employees, 'employee')]:
                    for row in db.scalars(select(model)):
                        if row.id not in records and row.sync_quality != 'pending_verification':
                            self._log(db, kind, row.id, {'sync_quality': row.sync_quality}, {'sync_quality': 'pending_verification'}, job_id, now)
                            row.sync_quality = 'pending_verification'; changes += 1
                state.last_full_sync_at = now
                state.coverage_status = candidate.coverage_status
                if candidate.pending: state.coverage_status='incomplete'
                if db.get(SystemSetting,'coverage_invalidated'): state.coverage_status='unknown'
                acceptance=db.get(SystemSetting,'coverage_acceptance')
                if acceptance:
                    accepted_at=json.loads(acceptance.value)['updated_at']
                    if not candidate.collection_started_at or datetime.fromisoformat(candidate.collection_started_at)<datetime.fromisoformat(accepted_at):
                        state.coverage_status='unknown'
                state.initialization_status = 'complete'
                if state.dataset_epoch == 'pending': state.dataset_epoch = uuid.uuid4().hex
            if changes:
                db.flush()
                StoreAdminService._rebuild_projection(db)
                state.data_version += 1
            if job:
                job.status, job.phase, job.lease_expires_at, job.updated_at = 'succeeded', 'published', None, now
                db.execute(delete(SyncStaging).where(SyncStaging.job_id == job_id))
            if event_id:
                event = db.get(EventInbox, event_id)
                event.status = 'failed' if candidate.pending else 'succeeded'
                event.attempts += 1
                if candidate.pending: event.payload={**event.payload,'error_code':'PENDING_VERIFICATION'}
                db.merge(SystemSetting(key='last_event_processed_at', value=now.isoformat()+'+00:00'))

    @staticmethod
    def _defer_unresolved(db,candidate,now):
        from dataclasses import replace
        known=set(db.scalars(select(Department.id)))
        departments=dict(candidate.departments)
        employees=dict(candidate.employees)
        pending=set(candidate.pending)
        deferred={}
        # 父引用缺失时递归延后依赖它的部门；已有部门保留原父引用。
        while True:
            available=known|set(departments)
            blocked={key for key,value in departments.items() if value.get('parent_unreadable') or value['parent_id'] and value['parent_id'] not in available}
            if not blocked: break
            for key in blocked:
                value=departments.pop(key)
                deferred[('department',key)]=value
                pending.add(('department',key))
                if value['parent_id']:pending.add(('department',value['parent_id']))
                if value['status']=='inactive' and key in known:
                    existing=db.get(Department,key)
                    departments[key]={'id':key,'parent_id':existing.parent_id,'status':'inactive','lifecycle_only':True}
        available=known|set(departments)
        for key,value in list(employees.items()):
            references=set(value['department_ids'] or [])
            if value['primary_department_id']: references.add(value['primary_department_id'])
            if value['department_ids'] is None or references-available:
                deferred[('employee',key)]=value
                if value['status']=='inactive':
                    employees[key]={**value,'lifecycle_only':True}
                else:
                    employees.pop(key)
                pending.add(('employee',key))
                pending.update(('department',identifier) for identifier in references-available)
        for kind,identifier in pending:
            previous=db.get(PendingFact,(kind,identifier))
            value=deferred.get((kind,identifier),previous.normalized_data if previous else {})
            db.merge(PendingFact(object_type=kind,source_id=identifier,normalized_data=value,error_code='PENDING_VERIFICATION',updated_at=now))
        for kind,records in [('department',departments),('employee',employees)]:
            for identifier in records:
                if (kind,identifier) not in pending:
                    db.execute(delete(PendingFact).where(PendingFact.object_type==kind,PendingFact.source_id==identifier))
        return replace(candidate,departments=departments,employees=employees,pending=sorted(pending))

    def _end_department_memberships(self,db,department_id,job_id,now):
        relations=list(db.scalars(select(EmployeeDepartment).where(EmployeeDepartment.department_id==department_id,EmployeeDepartment.active.is_(True))))
        for relation in relations:
            relation.active=False
            self._log(db,'membership',relation.employee_id,{'department_id':department_id,'active':True},{'department_id':department_id,'active':False},job_id,now)
        return len(relations)

    def _publish_inactive_lifecycle(self,db,value,job_id,now):
        """可信离职独立生效；未解析的新关系仍隔离，历史资料不覆盖。"""
        row=db.get(Employee,value['id'])
        if row is None:
            fields={k:v for k,v in value.items() if k not in {'department_ids','lifecycle_only'}}
            fields['primary_department_id']=None
        else:
            fields={'id':row.id,'status':'inactive'}
        fields['sync_quality']='pending_verification'
        changes=self._upsert(db,Employee,fields,'employee',job_id,now)
        db.flush()
        relations=list(db.scalars(select(EmployeeDepartment).where(EmployeeDepartment.employee_id==value['id'])))
        before=sorted((r.department_id,r.is_primary,r.active) for r in relations)
        changed=any(r.active for r in relations)
        for relation in relations: relation.active=False
        if changed:
            after=sorted((r.department_id,r.is_primary,False) for r in relations)
            self._log(db,'membership',value['id'],{'relations':before},{'relations':after},job_id,now)
            changes+=1
        self._revoke_employee_sessions(db,value['feishu_user_id'],job_id,now)
        return changes

    @staticmethod
    def _revoke_employee_sessions(db,user_id,job_id,now):
        identities=list(db.scalars(select(LoginIdentity).where(LoginIdentity.user_id==user_id).with_for_update()))
        for identity in identities:
            sessions=list(db.scalars(select(AdminSession).where(AdminSession.open_id==identity.open_id,AdminSession.revoked_at.is_(None)).with_for_update()))
            for session in sessions: session.revoked_at=now
            if sessions:
                db.add(ChangeLog(object_type='security',object_id=identity.open_id,source='feishu',actor='sync',job_id=job_id,before_data={'active_sessions':len(sessions)},after_data={'error_code':'EMPLOYEE_INACTIVE','active_sessions':0},committed_at=now))

    def _upsert(self, db, model, value, kind, job_id, now):
        row = db.get(model, value['id'])
        before = {key: getattr(row, key) for key in value} if row else None
        if before == value:
            row.last_seen_at = now
            return 0
        if row is None:
            row = model(**value); db.add(row)
        else:
            for key, item in value.items(): setattr(row, key, item)
        row.last_seen_at = now
        self._log(db, kind, value['id'], before, value, job_id, now)
        return 1

    @staticmethod
    def _log(db, kind, identifier, before, after, job_id, now):
        db.add(ChangeLog(object_type=kind, object_id=identifier, source='feishu', actor='sync', job_id=job_id, before_data=before, after_data=after, committed_at=now))
