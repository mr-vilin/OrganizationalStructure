from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from app.dependencies import Runtime, get_admin_identity, get_runtime, require_admin_write
from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, StoreProfile
from app.stores.domain import UNSET, InvalidStoreChanges, StorePatch
from app.stores.service import StoreAdminService
from app.web import utc_datetime
from app.config import get_settings


router = APIRouter(prefix="/admin/api")


@router.get("/status")
def admin_status(identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    import json
    from app.feishu.health import connection_summary
    from app.persistence.models import DatasetState, SystemSetting, EventInbox
    from sqlalchemy import func
    settings=get_settings()
    try:
        data, meta = runtime.reads.status()
    except RuntimeError as exc:
        if str(exc) != 'INITIALIZATION_INCOMPLETE': raise
        with runtime.sessions() as db:
            state=db.get(DatasetState,1)
            data={'initialization_status':'pending','coverage_status':'unknown'}
            meta={'dataset_epoch':state.dataset_epoch if state else 'pending','data_version':state.data_version if state else 0}
    with runtime.sessions() as db:
        observation=db.get(SystemSetting,'feishu_connection_observation')
        processed=db.get(SystemSetting,'last_event_processed_at')
        data['connection']=connection_summary(settings,json.loads(observation.value) if observation else None)
        data['last_event_processed_at']=processed.value if processed else None
        data['failed_event_count']=db.scalar(select(func.count()).select_from(EventInbox).where(EventInbox.status=='failed')) or 0
    data['coverage_acceptance']={'reference':settings.coverage_acceptance_reference,'all_members_verified':settings.coverage_all_members_verified,'departmentless_verified':settings.coverage_departmentless_verified}
    from app.sync.coverage import CoverageService
    persisted=CoverageService(runtime.sessions).get()
    if persisted: data['coverage_acceptance']=persisted
    return {"data": data, "meta": meta}


class ReconcileSchedule(BaseModel):
    enabled: bool = Field(strict=True)
    local_time: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    timezone: str = Field(pattern=r'^Asia/Shanghai$')


@router.get('/settings/reconcile-schedule')
def get_schedule(identity=Depends(get_admin_identity),runtime=Depends(get_runtime)):
    from app.sync.settings import ScheduleService
    return {'data':ScheduleService(runtime.sessions).get(),'meta':{}}


@router.put('/settings/reconcile-schedule')
def put_schedule(body: ReconcileSchedule,authorization=Depends(require_admin_write),runtime=Depends(get_runtime)):
    from app.sync.settings import ScheduleService
    identity,_=authorization
    return {'data':ScheduleService(runtime.sessions).put(body.model_dump(),f'admin:{identity.open_id}'),'meta':{}}


@router.get("/departments")
def admin_departments(parent_id: str | None = None, root_id: str | None = None, include_descendants: bool = False, include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.list_departments(parent_id=parent_id, root_id=root_id, include_descendants=include_descendants, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)
    return {"data": data, "meta": meta}


@router.get("/departments/{department_id}")
def admin_department(department_id: str, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.get_department(department_id)
    if data is None:
        raise HTTPException(404, {"code": "DEPARTMENT_NOT_FOUND", "message": "部门不存在"})
    return {"data": data, "meta": meta}


@router.get("/employees")
def admin_employees(department_id: str | None = None, include_descendants: bool = False, store_id: str | None = None, primary_store_id: str | None = None, include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.list_employees(department_id=department_id, include_descendants=include_descendants, store_id=store_id, primary_store_id=primary_store_id, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)
    return {"data": data, "meta": meta}


@router.get("/employees/{employee_id}")
def admin_employee(employee_id: str, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.get_employee(employee_id)
    if data is None:
        raise HTTPException(404, {"code": "EMPLOYEE_NOT_FOUND", "message": "员工不存在"})
    return {"data": data, "meta": meta}


@router.get("/stores")
def admin_stores(include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.list_stores(include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)
    return {"data": data, "meta": meta}


@router.get("/stores/{store_id}")
def admin_store(store_id: str, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.get_store(store_id)
    if data is None:
        raise HTTPException(404, {"code": "STORE_NOT_FOUND", "message": "门店不存在"})
    return {"data": data, "meta": meta}


@router.get("/stores/{store_id}/employees")
def admin_store_employees(store_id: str, membership: str = Query("all", pattern="^(all|primary)$"), include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.list_store_employees(store_id, membership=membership, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)
    return {"data": data, "meta": meta}


class StoreChange(BaseModel):
    department_id: str = Field(min_length=1, max_length=191)
    is_store: bool
    store_code: str | None = Field(default=None, max_length=128)
    notes: str | None = None


class StoreBatch(BaseModel):
    data_version: int
    changes: list[StoreChange] = Field(min_length=1, max_length=500)


def _patches(body: StoreBatch) -> list[StorePatch]:
    return [StorePatch(
        department_id=change.department_id,
        is_store=change.is_store,
        store_code=change.store_code if "store_code" in change.model_fields_set else UNSET,
        notes=change.notes if "notes" in change.model_fields_set else UNSET,
    ) for change in body.changes]


def _store_error(exc: InvalidStoreChanges):
    raise HTTPException(422, {"code": "INVALID_STORE_CHANGES", "message": "门店修改无效", "fields": [error.__dict__ for error in exc.errors]})


@router.post("/stores/batch/preview")
def preview_stores(body: StoreBatch, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    try:
        data = StoreAdminService(runtime.sessions).preview(_patches(body), body.data_version)
    except InvalidStoreChanges as exc:
        _store_error(exc)
    return {"data": data, "meta": {"data_version": data["data_version"]}}


@router.post("/stores/batch/apply")
def apply_stores(body: StoreBatch, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    identity, _ = authorization
    try:
        data = StoreAdminService(runtime.sessions).apply(_patches(body), body.data_version, f"admin:{identity.open_id}", datetime.now(timezone.utc).replace(tzinfo=None))
    except InvalidStoreChanges as exc:
        _store_error(exc)
    return {"data": data, "meta": {"data_version": data["data_version"]}}


@router.patch("/stores/{store_id}")
def patch_store(store_id: str, body: StoreChange, data_version: int, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    if body.department_id != store_id:
        raise HTTPException(422, {"code": "STORE_ID_MISMATCH", "message": "路径与请求中的部门 ID 不一致"})
    return apply_stores(StoreBatch(data_version=data_version, changes=[body]), authorization, runtime)


@router.get("/change-logs")
def change_logs(object_type: str | None = None, object_id: str | None = None, source: str | None = None, job_id: str | None = None, actor: str | None = None, action: str | None = None, committed_after: datetime | None = None, committed_before: datetime | None = None, limit: int = Query(100, ge=1, le=500), cursor: int | None = None, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    if action not in (None,'create','update','delete'):
        raise HTTPException(422,{'code':'VALIDATION_ERROR','message':'action 必须为 create/update/delete'})
    for boundary in (committed_after,committed_before):
        if boundary is not None and boundary.tzinfo is None:
            raise HTTPException(422,{'code':'VALIDATION_ERROR','message':'日志时间必须包含 UTC 时区'})
    with runtime.sessions() as db:
        stmt = select(ChangeLog).order_by(ChangeLog.id.desc()).limit(limit + 1)
        for column, value in ((ChangeLog.object_type, object_type), (ChangeLog.object_id, object_id), (ChangeLog.source, source), (ChangeLog.job_id, job_id), (ChangeLog.actor,actor)):
            if value is not None:
                stmt = stmt.where(column == value)
        from sqlalchemy import JSON, or_, not_
        before_null=or_(ChangeLog.before_data.is_(None),ChangeLog.before_data==JSON.NULL)
        after_null=or_(ChangeLog.after_data.is_(None),ChangeLog.after_data==JSON.NULL)
        if action=='create': stmt=stmt.where(before_null)
        if action=='delete': stmt=stmt.where(after_null,not_(before_null))
        if action=='update': stmt=stmt.where(not_(before_null),not_(after_null))
        if committed_after: stmt=stmt.where(ChangeLog.committed_at>=committed_after.astimezone(timezone.utc).replace(tzinfo=None))
        if committed_before: stmt=stmt.where(ChangeLog.committed_at<=committed_before.astimezone(timezone.utc).replace(tzinfo=None))
        if cursor is not None:
            stmt = stmt.where(ChangeLog.id < cursor)
        rows = list(db.scalars(stmt))
        page = rows[:limit]
        data = [{"id": row.id, "object_type": row.object_type, "object_id": row.object_id, "source": row.source, "actor": row.actor, "job_id": row.job_id, "before": row.before_data, "after": row.after_data, "committed_at": utc_datetime(row.committed_at)} for row in page]
        for item in data: item['action']='create' if item['before'] is None else 'delete' if item['after'] is None else 'update'
        return {"data": data, "meta": {"next_cursor": str(page[-1].id) if len(rows) > limit else None}}


@router.get('/sync/events')
def list_events(status: str | None = None,limit: int=Query(100,ge=1,le=500),cursor: str | None=None,identity=Depends(get_admin_identity),runtime=Depends(get_runtime)):
    from app.persistence.models import EventInbox
    with runtime.sessions() as db:
        stmt=select(EventInbox).order_by(EventInbox.event_id).limit(limit+1)
        if status: stmt=stmt.where(EventInbox.status==status)
        if cursor: stmt=stmt.where(EventInbox.event_id>cursor)
        rows=list(db.scalars(stmt)); page=rows[:limit]
        return {'data':[{'event_id':r.event_id,'event_type':r.event_type,'object_id':r.object_id,'status':r.status,'attempts':r.attempts,'received_at':utc_datetime(r.received_at),'error_code':r.payload.get('error_code')} for r in page],'meta':{'next_cursor':page[-1].event_id if len(rows)>limit else None}}


@router.post('/sync/events/{event_id}/retry',status_code=202)
def retry_event(event_id: str,authorization=Depends(require_admin_write),runtime=Depends(get_runtime)):
    from app.persistence.models import EventInbox
    with runtime.sessions.begin() as db:
        row=db.scalar(select(EventInbox).where(EventInbox.event_id==event_id).with_for_update())
        if not row or row.status!='failed' or not row.object_id:
            raise HTTPException(409,{'code':'EVENT_NOT_RETRYABLE','message':'事件未失败或缺少对象标识，请全量核对并核查应用权限'})
        row.status='queued'
        row.payload={k:v for k,v in row.payload.items() if k!='error_code'}
        db.add(ChangeLog(object_type='event',object_id=event_id,source='admin',actor=f'admin:{authorization[0].open_id}',before_data={'status':'failed'},after_data={'status':'queued'},committed_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    return {'data':{'event_id':event_id,'status':'queued'},'meta':{}}


class AllowlistEntry(BaseModel):
    open_id: str = Field(min_length=1, max_length=191)

    @field_validator("open_id")
    @classmethod
    def normalized_open_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("open_id 不能为空")
        return value


@router.get("/admin-allowlist")
def list_allowlist(identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    with runtime.sessions() as db:
        rows = list(db.scalars(select(AdminAllowlist).order_by(AdminAllowlist.open_id)))
        return {"data": [{"open_id": row.open_id, "created_at": utc_datetime(row.created_at)} for row in rows], "meta": {}}


@router.post("/admin-allowlist", status_code=201)
def add_allowlist(body: AllowlistEntry, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    identity, _ = authorization
    runtime.identities.add_admin(body.open_id, f"admin:{identity.open_id}", now)
    return {"data": {"open_id": body.open_id, "created_at": utc_datetime(now)}, "meta": {}}


@router.delete("/admin-allowlist/{open_id}")
def delete_allowlist(open_id: str, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    identity, _ = authorization
    if not runtime.identities.remove_admin(open_id, f"admin:{identity.open_id}", now):
        raise HTTPException(404, {"code": "ADMIN_NOT_FOUND", "message": "管理员不在白名单中"})
    return {"data": {"open_id": open_id, "deleted": True}, "meta": {}}


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name 不能为空")
        return value


@router.get("/api-clients")
def list_clients(identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    with runtime.sessions() as db:
        rows = list(db.scalars(select(ApiClient).order_by(ApiClient.created_at, ApiClient.id)))
        return {"data": [{"client_id": row.id, "name": row.name, "created_at": utc_datetime(row.created_at), "revoked_at": utc_datetime(row.revoked_at)} for row in rows], "meta": {}}


@router.post("/api-clients", status_code=201)
def create_client(body: ClientCreate, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    identity, _ = authorization
    record, secret = runtime.identities.create_api_key(body.name, f"admin:{identity.open_id}", datetime.now(timezone.utc).replace(tzinfo=None))
    return {"data": {"client_id": record.id, "name": record.name, "secret": secret, "created_at": utc_datetime(record.created_at)}, "meta": {"secret_shown_once": True}}


@router.post("/api-clients/{client_id}/rotate")
def rotate_client(client_id: str, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    identity, _ = authorization
    result = runtime.identities.rotate_api_key(client_id, f"admin:{identity.open_id}", now)
    if result is None:
        raise HTTPException(404, {"code": "API_CLIENT_NOT_FOUND", "message": "API 客户端不存在或已撤销"})
    record, secret = result
    return {"data": {"client_id": record.id, "name": record.name, "secret": secret, "created_at": utc_datetime(record.created_at)}, "meta": {"secret_shown_once": True, "replaces_client_id": client_id}}


@router.post("/api-clients/{client_id}/revoke")
def revoke_client(client_id: str, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    identity, _ = authorization
    if not runtime.identities.revoke_api_key_audited(client_id, f"admin:{identity.open_id}", datetime.now(timezone.utc).replace(tzinfo=None)):
        raise HTTPException(404, {"code": "API_CLIENT_NOT_FOUND", "message": "API 客户端不存在"})
    return {"data": {"client_id": client_id, "revoked": True}, "meta": {}}
