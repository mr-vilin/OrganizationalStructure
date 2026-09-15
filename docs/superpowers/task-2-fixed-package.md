# Task2 backend snapshot, no Git baseline

## backend/alembic.ini
```
[alembic]
script_location = migrations
prepend_sys_path = .
sqlalchemy.url = mysql+pymysql://unused:unused@localhost/unused

[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s


```

## backend/app/__init__.py
```
"""组织目录后端。"""


```

## backend/app/admin/__init__.py
```


```

## backend/app/admin/router.py
```
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
        return {"data": data, "meta": {"next_cursor": page[-1].id if len(rows) > limit else None}}


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

```

## backend/app/config.py
```
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORG_", case_sensitive=False, extra="ignore")

    database_url: str | None = None
    session_secret: SecretStr | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: SecretStr | None = None
    feishu_redirect_uri: str | None = None
    feishu_tenant_key: str | None = None
    feishu_scopes: str = ""
    coverage_acceptance_reference: str = ""
    coverage_all_members_verified: bool = False
    coverage_departmentless_verified: bool = False
    initial_admin_open_ids: str = ""

    @property
    def admin_open_ids(self) -> set[str]:
        return {value.strip() for value in self.initial_admin_open_ids.split(",") if value.strip()}

    @property
    def identity_ready(self) -> bool:
        return all((self.session_secret, self.feishu_app_id, self.feishu_app_secret, self.feishu_redirect_uri, self.feishu_tenant_key))


@lru_cache
def get_settings() -> Settings:
    return Settings()

```

## backend/app/dependencies.py
```
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import Cookie, Depends, Header, HTTPException, Request

from .config import get_settings
from .persistence.database import create_mysql_engine, session_factory
from .persistence.read_service import SqlReadService
from .persistence.repositories import SqlIdentityRepository, SqlSyncJobRepository
from .services import UninitializedReadService


@dataclass(frozen=True)
class Runtime:
    engine: object
    sessions: object
    reads: SqlReadService
    identities: SqlIdentityRepository
    jobs: SqlSyncJobRepository


@lru_cache
def get_runtime() -> Runtime | None:
    settings = get_settings()
    if not settings.database_url or not settings.session_secret:
        return None
    engine = create_mysql_engine(settings.database_url)
    sessions = session_factory(engine)
    pepper = settings.session_secret.get_secret_value()
    return Runtime(engine, sessions, SqlReadService(sessions, pepper), SqlIdentityRepository(sessions, pepper), SqlSyncJobRepository(sessions))


def get_read_service():
    runtime = get_runtime()
    return runtime.reads if runtime else UninitializedReadService()


def get_public_identity(authorization: str | None = Header(default=None), runtime: Runtime | None = Depends(get_runtime)):
    if runtime is not None and authorization and authorization.startswith("Bearer "):
        try:
            client_id, secret = authorization[7:].split(".", 1)
        except ValueError:
            pass
        else:
            identity = runtime.identities.authenticate_api_key(client_id, secret)
            if identity is not None:
                return identity
    raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "只读 API 凭据无效"})


def get_admin_identity(org_session: str | None = Cookie(default=None), runtime: Runtime | None = Depends(get_runtime)):
    if runtime is not None and org_session:
        identity = runtime.identities.authenticate_session(org_session, datetime.now(timezone.utc).replace(tzinfo=None))
        if identity is not None:
            return identity
    raise HTTPException(status_code=401, detail={"code": "ADMIN_SESSION_REQUIRED", "message": "需要管理员会话"})


def require_admin_write(identity=Depends(get_admin_identity), x_csrf_token: str | None = Header(default=None), settings=Depends(get_settings)):
    secret = settings.session_secret.get_secret_value() if settings.session_secret else ""
    digest = hmac.new(secret.encode(), (x_csrf_token or "").encode(), hashlib.sha256).hexdigest()
    if not x_csrf_token or not hmac.compare_digest(identity.csrf_hash, digest):
        raise HTTPException(status_code=403, detail={"code": "CSRF_REQUIRED", "message": "缺少 CSRF 令牌"})
    return identity, x_csrf_token

```

## backend/app/directory/__init__.py
```
from .domain import Department, Employee, Membership, StoreResolution, resolve_employee_stores

__all__ = ["Department", "Employee", "Membership", "StoreResolution", "resolve_employee_stores"]


```

## backend/app/directory/domain.py
```
from dataclasses import dataclass


@dataclass(frozen=True)
class Department:
    id: str
    parent_id: str | None
    is_store: bool
    status: str = "active"
    sync_quality: str = "complete"


@dataclass(frozen=True)
class Employee:
    id: str
    status: str
    primary_department_id: str | None
    sync_quality: str = "complete"


@dataclass(frozen=True)
class Membership:
    employee_id: str
    department_id: str
    active: bool = True


@dataclass(frozen=True)
class StoreResolution:
    store_ids: list[str]
    primary_store_id: str | None
    primary_store_status: str


def _nearest_store(department_id: str, departments: dict[str, Department]) -> tuple[str | None, bool]:
    current_id: str | None = department_id
    visited: set[str] = set()
    while current_id is not None:
        if current_id in visited:
            return None, False
        visited.add(current_id)
        department = departments.get(current_id)
        if department is None:
            return None, False
        if department.sync_quality in {"pending_verification", "unknown", "inconsistent"}:
            return None, False
        if department.status == "active" and department.is_store:
            return department.id, True
        current_id = department.parent_id
    return None, True


def resolve_employee_stores(
    employee: Employee,
    memberships: list[Membership],
    departments: dict[str, Department],
) -> StoreResolution:
    if employee.status != "active":
        return StoreResolution([], None, "inactive")

    active_department_ids = [
        relation.department_id
        for relation in memberships
        if relation.active and relation.employee_id == employee.id
    ]
    stores: list[str] = []
    for department_id in active_department_ids:
        store_id, _ = _nearest_store(department_id, departments)
        if store_id is not None and store_id not in stores:
            stores.append(store_id)

    primary = employee.primary_department_id
    if employee.sync_quality == "inconsistent":
        return StoreResolution(stores, None, "inconsistent")
    if primary is None:
        return StoreResolution(stores, None, "unknown")
    if primary not in active_department_ids:
        return StoreResolution(stores, None, "inconsistent")
    primary_store, complete = _nearest_store(primary, departments)
    if not complete:
        return StoreResolution(stores, None, "unknown")
    if primary_store is None:
        return StoreResolution(stores, None, "not_in_store")
    return StoreResolution(stores, primary_store, "resolved")

```

## backend/app/feishu/__init__.py
```
"""飞书只读适配器。"""

```

## backend/app/feishu/binding.py
```
from sqlalchemy import select
from app.persistence.models import FeishuConnection, SystemSetting


def bind_connection(sessions,app_id,tenant_key):
    if not app_id or not tenant_key: raise RuntimeError('IDENTITY_NOT_CONFIGURED')
    with sessions.begin() as db:
        lock=db.scalar(select(SystemSetting).where(SystemSetting.key=='task_queue_lock').with_for_update())
        if lock is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
        row=db.scalar(select(FeishuConnection).where(FeishuConnection.id==1).with_for_update())
        if row is None:
            db.add(FeishuConnection(id=1,app_id=app_id,tenant_key=tenant_key,status='degraded',coverage_status='unknown'))
        elif row.app_id!=app_id or row.tenant_key!=tenant_key:
            raise RuntimeError('CONFIG_BINDING_MISMATCH')

```

## backend/app/feishu/client.py
```
import time
from urllib.parse import quote

import httpx


class FeishuClient:
    """自建应用；只暴露脱敏错误，不记录响应正文或凭据。"""
    def __init__(self, app_id, app_secret, http=None):
        self.app_id, self.app_secret = app_id, app_secret
        self.http = http or httpx.Client(timeout=20, follow_redirects=False)
        self.tokens = {}

    def _request(self, method, path, token=None, **kwargs):
        try:
            response = self.http.request(method, 'https://open.feishu.cn/open-apis/' + path, headers={'Authorization': 'Bearer ' + token} if token else {}, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if payload.get('code') != 0:
                raise RuntimeError('FEISHU_API_ERROR')
            return payload
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RuntimeError('FEISHU_UNAVAILABLE') from None

    def _token(self, kind):
        cached = self.tokens.get(kind)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        data = self._request('POST', f'auth/v3/{kind}_access_token/internal', json={'app_id': self.app_id, 'app_secret': self.app_secret})
        token = data.get(f'{kind}_access_token')
        if not token:
            raise RuntimeError('FEISHU_TOKEN_MISSING')
        self.tokens[kind] = (token, time.monotonic() + max(0, int(data.get('expire', 0)) - 120))
        return token

    def login(self, code):
        data = self._request('POST', 'authen/v1/oidc/access_token', self._token('app'), json={'grant_type': 'authorization_code', 'code': code}).get('data', {})
        if not data.get('access_token'):
            raise RuntimeError('FEISHU_TOKEN_MISSING')
        return self._request('GET', 'authen/v1/user_info', data['access_token']).get('data', {})

    def pages(self, resource, **params):
        identifier = params.pop('department_id', None)
        path = {'scopes': 'scopes', 'users': 'users/find_by_department', 'children': f'departments/{quote(str(identifier), safe="")}/children'}[resource]
        query = {'user_id_type': 'user_id', 'department_id_type': 'open_department_id', 'page_size': 50, **params}
        if resource == 'users':
            query['department_id'] = identifier
        if resource == 'children':
            query['fetch_child'] = 'false'
        seen = set()
        while True:
            data = self._request('GET', 'contact/v3/' + path, self._token('tenant'), params=query).get('data')
            if not isinstance(data, dict) or not isinstance(data.get('has_more'), bool):
                raise RuntimeError('INVALID_PAGINATION')
            yield data
            if not data['has_more']:
                break
            token = data.get('page_token')
            if not token or token in seen:
                raise RuntimeError('INVALID_PAGINATION')
            seen.add(token)
            query['page_token'] = token

    def detail(self, kind, identifier):
        path = 'users' if kind == 'user' else 'departments'
        data = self._request('GET', f'contact/v3/{path}/{quote(identifier, safe="")}', self._token('tenant'), params={'user_id_type': 'user_id', 'department_id_type': 'open_department_id'}).get('data', {}).get(kind)
        if not isinstance(data, dict):
            raise RuntimeError('FEISHU_DETAIL_MISSING')
        if data.get('user_id' if kind == 'user' else 'open_department_id') != identifier:
            raise RuntimeError('FEISHU_ID_MISMATCH')
        return data

```

## backend/app/feishu/events.py
```
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from app.persistence.models import EventInbox, DatasetState, SystemSetting

EVENT_TYPES = tuple(f'contact.{kind}.{action}_v3' for kind in ('user', 'department') for action in ('created', 'updated', 'deleted')) + ('contact.scope.updated_v3',)


def normalize_event(payload, app_id, tenant_key):
    header = payload.get('header') or {}
    if not app_id or not tenant_key or header.get('app_id') != app_id or header.get('tenant_key') != tenant_key:
        raise ValueError('EVENT_IDENTITY_MISMATCH')
    if not header.get('event_id') or header.get('event_type') not in EVENT_TYPES:
        raise ValueError('EVENT_HEADER_INVALID')
    kind = 'user_id' if '.user.' in header['event_type'] else 'open_department_id'
    obj = (payload.get('event') or {}).get('object') or {}
    identifier = obj.get(kind)
    if header['event_type'] == 'contact.scope.updated_v3': identifier = 'scope'
    # 仅保存处理需要的字段，剔除 header token 与用户联系资料。
    stored = {'header': {k: header.get(k) for k in ('event_id', 'event_type', 'app_id', 'tenant_key', 'create_time')}, 'object': {k: obj.get(k) for k in (kind, 'open_id', 'status')}}
    if not identifier:
        stored['error_code'] = 'EVENT_OBJECT_ID_MISSING'
    return {'event_id': header['event_id'], 'event_type': header['event_type'], 'object_id': identifier, 'payload': stored, 'status': 'queued' if identifier else 'failed'}


def receive(sessions, payload, app_id, tenant_key):
    row = normalize_event(payload, app_id, tenant_key)
    try:
        with sessions.begin() as db:
            db.add(EventInbox(**row, attempts=0, received_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            if row['event_type'] == 'contact.scope.updated_v3':
                state=db.scalar(select(DatasetState).where(DatasetState.id==1).with_for_update())
                if state: state.coverage_status='unknown'
                db.merge(SystemSetting(key='coverage_invalidated',value='true'))
    except IntegrityError:
        with sessions() as db:
            if db.get(EventInbox, row['event_id']) is None:
                raise
    return row

```

## backend/app/feishu/health.py
```
import json
from datetime import datetime, timezone, timedelta
from app.persistence.models import SystemSetting


def connection_summary(settings, observation):
    configured = bool(settings.feishu_app_id and settings.feishu_app_secret and settings.feishu_tenant_key)
    status = 'degraded' if configured else 'unconfigured'
    checked_at = observation.get('checked_at') if observation else None
    if configured and observation and observation.get('status') == 'connected' and checked_at:
        checked = datetime.fromisoformat(checked_at)
        if datetime.now(timezone.utc) - checked < timedelta(seconds=90): status = 'connected'
    def mask(value): return ('***'+value[-4:]) if value else None
    return {'status': status, 'checked_at': checked_at, 'app_id_masked': mask(settings.feishu_app_id), 'tenant_key_masked': mask(settings.feishu_tenant_key), 'scopes': [s.strip() for s in settings.feishu_scopes.split(',') if s.strip()]}


def observe(sessions, status):
    with sessions.begin() as db:
        db.merge(SystemSetting(key='feishu_connection_observation', value=json.dumps({'status':status,'checked_at':datetime.now(timezone.utc).isoformat()})))

```

## backend/app/feishu/listener.py
```
"""SDK 1.7.3 同步长连接独立进程。回调仅校验和短事务入箱。"""
import json
from datetime import datetime, timezone
from app.feishu.events import receive, EVENT_TYPES
from app.feishu.health import observe
from app.persistence.repositories import SqlSyncJobRepository


class Listener:
    def __init__(self,sessions,settings): self.sessions,self.settings=sessions,settings

    def starting(self):
        observe(self.sessions,'degraded')
        self._reconcile('listener:startup')

    def _reconcile(self,reason):
        SqlSyncJobRepository(self.sessions).submit('reconcile',None,reason,datetime.now(timezone.utc).replace(tzinfo=None))

    def reconnecting(self): observe(self.sessions,'degraded')

    def reconnected(self):
        self._reconcile('listener:reconnected')
        observe(self.sessions,'connected')

    def receive(self,payload):
        result=receive(self.sessions,payload,self.settings.feishu_app_id,self.settings.feishu_tenant_key)
        observe(self.sessions,'connected')
        return result


def main():
    from app.config import get_settings
    from app.dependencies import get_runtime
    settings,runtime=get_settings(),get_runtime()
    if not runtime or not settings.feishu_app_id or not settings.feishu_app_secret or not settings.feishu_tenant_key:
        raise SystemExit('长连接未配置：需要数据库、会话密钥、飞书应用与租户配置')
    from app.feishu.binding import bind_connection
    bind_connection(runtime.sessions,settings.feishu_app_id,settings.feishu_tenant_key)
    import lark_oapi as lark
    listener=Listener(runtime.sessions,settings)
    def callback(data):
        # SDK 模型序列化后提取白名单字段，绝不在此执行远程查询。
        listener.receive(json.loads(lark.JSON.marshal(data)))
    builder=lark.EventDispatcherHandler.builder('','')
    for name in EVENT_TYPES:
        getattr(builder,'register_p2_'+name.replace('.','_'))(callback)
    client=lark.ws.Client(settings.feishu_app_id,settings.feishu_app_secret.get_secret_value(),event_handler=builder.build(),log_level=lark.LogLevel.ERROR)
    client.on_reconnecting=listener.reconnecting
    client.on_reconnected=listener.reconnected
    listener.starting()
    # 首次连接没有公开通知；不读取私有字段，也不虚报 connected。
    client.start()


if __name__=='__main__': main()

```

## backend/app/feishu/oauth.py
```
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from app.persistence.models import OAuthState, LoginIdentity, AdminAllowlist, AdminSession, Employee, ChangeLog


class OAuthService:
    def __init__(self, sessions, settings, api):
        from app.feishu.binding import bind_connection
        bind_connection(sessions,settings.feishu_app_id,settings.feishu_tenant_key)
        self.sessions, self.settings, self.api = sessions, settings, api

    def begin(self):
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            db.execute(delete(OAuthState).where(OAuthState.expires_at < now))
            db.add(OAuthState(digest=hashlib.sha256(state.encode()).hexdigest(), expires_at=now + timedelta(minutes=10)))
        return state

    def complete(self, state, cookie, code):
        if not state or not cookie or not hmac.compare_digest(state, cookie):
            raise ValueError('OAUTH_STATE_INVALID')
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            record = db.scalar(select(OAuthState).where(OAuthState.digest == hashlib.sha256(state.encode()).hexdigest()).with_for_update())
            if not record or record.expires_at <= now:
                raise ValueError('OAUTH_STATE_INVALID')
            db.delete(record)
        identity = self.api.login(code)
        if identity.get('tenant_key') != self.settings.feishu_tenant_key or not identity.get('open_id') or not identity.get('user_id'):
            raise ValueError('OAUTH_IDENTITY_MISMATCH')
        csrf = secrets.token_urlsafe(32)
        failure = None
        with self.sessions.begin() as db:
            if db.scalar(select(AdminAllowlist).where(AdminAllowlist.open_id == identity['open_id']).with_for_update()) is None:
                raise ValueError('ADMIN_NOT_ALLOWED')
            existing = db.scalar(select(LoginIdentity).where(LoginIdentity.open_id==identity['open_id']).with_for_update())
            employee = db.scalar(select(Employee).where(Employee.feishu_user_id==identity['user_id']).with_for_update())
            if existing and (existing.user_id!=identity['user_id'] or existing.tenant_key!=identity['tenant_key']):
                failure='LOGIN_IDENTITY_MISMATCH'
            elif employee and employee.status=='inactive':
                failure='EMPLOYEE_INACTIVE'
            if failure:
                db.add(ChangeLog(object_type='security',object_id=identity['open_id'],source='oauth',actor=None,before_data=None,after_data={'error_code':failure},committed_at=now))
            else:
                if existing is None: db.add(LoginIdentity(open_id=identity['open_id'],user_id=identity['user_id'],tenant_key=identity['tenant_key']))
                session = AdminSession(id=secrets.token_urlsafe(32), open_id=identity['open_id'], csrf_hash=hmac.new(self.settings.session_secret.get_secret_value().encode(), csrf.encode(), hashlib.sha256).hexdigest(), expires_at=now+timedelta(hours=12))
                db.add(session)
        # 先提交安全事件，再拒绝；不要随业务异常回滚审计。
        if failure: raise ValueError(failure)
        return session, csrf

```

## backend/app/identity/__init__.py
```
from .services import ApiCredentialService, SessionService

__all__ = ["ApiCredentialService", "SessionService"]


```

## backend/app/identity/services.py
```
import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class SessionIdentity:
    open_id: str
    session_id: str
    csrf_digest: str
    expires_at: datetime


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str


class SessionService:
    def __init__(self, secret: str, allowlist: set[str], ttl: timedelta = timedelta(hours=12)):
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        self._secret = secret.encode()
        self._allowlist = set(allowlist)
        self._ttl = ttl
        self._revoked: set[str] = set()

    def set_allowlist(self, allowlist: set[str]) -> None:
        self._allowlist = set(allowlist)

    def create(self, open_id: str, now: datetime | None = None) -> IssuedSession | None:
        if open_id not in self._allowlist:
            return None
        now = now or datetime.now(timezone.utc)
        session_id, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        payload = {"oid": open_id, "sid": session_id, "csrf": self._digest(csrf), "exp": int((now + self._ttl).timestamp())}
        raw = _b64(json.dumps(payload, separators=(",", ":")).encode())
        signature = _b64(hmac.new(self._secret, raw.encode(), hashlib.sha256).digest())
        return IssuedSession(f"{raw}.{signature}", csrf)

    def authenticate(self, token: str | None, now: datetime | None = None) -> SessionIdentity | None:
        if not token:
            return None
        now = now or datetime.now(timezone.utc)
        try:
            raw, provided_signature = token.split(".", 1)
            expected = _b64(hmac.new(self._secret, raw.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(provided_signature, expected):
                return None
            payload = json.loads(_unb64(raw))
            expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        except (ValueError, KeyError, json.JSONDecodeError):
            return None
        if expires <= now or payload["sid"] in self._revoked or payload["oid"] not in self._allowlist:
            return None
        return SessionIdentity(payload["oid"], payload["sid"], payload["csrf"], expires)

    def revoke(self, session_id: str) -> None:
        self._revoked.add(session_id)

    def verify_csrf(self, identity: SessionIdentity, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(identity.csrf_digest, self._digest(token))

    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ApiClientRecord:
    client_id: str
    name: str
    secret_hash: str
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class IssuedApiCredential:
    client_id: str
    secret: str


class ApiCredentialService:
    def __init__(self, pepper: str):
        self._pepper = pepper.encode()
        self._records: dict[str, ApiClientRecord] = {}

    def issue(self, name: str, now: datetime | None = None) -> IssuedApiCredential:
        now = now or datetime.now(timezone.utc)
        client_id, secret = secrets.token_urlsafe(12), secrets.token_urlsafe(32)
        record = ApiClientRecord(client_id, name.strip(), self._hash(secret), now)
        self._records[client_id] = record
        return IssuedApiCredential(client_id, secret)

    def authenticate(self, client_id: str, secret: str, now: datetime | None = None) -> ApiClientRecord | None:
        record = self._records.get(client_id)
        if record is None or record.revoked_at is not None:
            return None
        return record if hmac.compare_digest(record.secret_hash, self._hash(secret)) else None

    def revoke(self, client_id: str, now: datetime | None = None) -> None:
        record = self._records.get(client_id)
        if record is not None:
            self._records[client_id] = ApiClientRecord(record.client_id, record.name, record.secret_hash, record.created_at, now or datetime.now(timezone.utc))

    def rotate(self, client_id: str, now: datetime | None = None) -> IssuedApiCredential:
        record = self._records[client_id]
        self.revoke(client_id, now)
        return self.issue(record.name, now)

    def export_records(self) -> list[ApiClientRecord]:
        return list(self._records.values())

    def _hash(self, secret: str) -> str:
        salt = hashlib.sha256(self._pepper).digest()
        return hashlib.scrypt(secret.encode(), salt=salt, n=2**14, r=8, p=1).hex()


```

## backend/app/main.py
```
from datetime import datetime

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError, OperationalError, InterfaceError, DisconnectionError, TimeoutError as SQLTimeoutError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from .config import Settings, get_settings
from .dependencies import Runtime, get_admin_identity, get_public_identity, get_read_service, get_runtime, require_admin_write
from .persistence.database import database_ready
from .services import ReadService
from .admin.router import router as admin_router


app = FastAPI(title="组织架构维护系统", version="1.0.0")
app.include_router(admin_router)


def error(code: str, message: str, status: int, *, fields: list | None = None) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return JSONResponse(body, status_code=status)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return error(detail.get("code", "HTTP_ERROR"), detail.get("message", "请求失败"), exc.status_code, fields=detail.get("fields"))


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    # 不序列化或记录异常原文，原文可能包含 SQL、参数和数据库地址。
    unavailable=isinstance(exc,(OperationalError,InterfaceError,DisconnectionError,SQLTimeoutError))
    return error('DATABASE_UNAVAILABLE' if unavailable else 'DATABASE_ERROR','数据库暂时不可用' if unavailable else '数据库操作失败',503 if unavailable else 500)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    fields = [{"loc": item.get("loc"), "type": item.get("type"), "msg": item.get("msg")} for item in exc.errors()]
    return error("VALIDATION_ERROR", "请求参数无效", 422, fields=fields)


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    if str(exc)=='CONFIG_BINDING_MISMATCH':
        return error('CONFIG_BINDING_MISMATCH','当前应用或租户与数据库绑定不一致',503)
    if str(exc) == "INITIALIZATION_INCOMPLETE":
        return error("INITIALIZATION_INCOMPLETE", "组织数据尚未完成初始化", 503)
    if str(exc) == "DATASET_CHANGED":
        return error("DATASET_CHANGED", "读取期间数据版本已变化，请重新开始分页", 409)
    if str(exc) == "INVALID_CURSOR":
        return error("INVALID_CURSOR", "分页游标无效或与筛选条件不匹配", 400)
    if str(exc) == "DATABASE_SCHEMA_INCOMPLETE":
        return error("DATABASE_SCHEMA_INCOMPLETE", "数据库迁移或系统单例种子不完整", 503)
    return error("INTERNAL_ERROR", "服务暂时不可用", 500)


@app.get("/health/live")
def live():
    return {"data": {"status": "ok"}, "meta": {}}


@app.get("/health/ready")
def ready(runtime: Runtime | None = Depends(get_runtime)):
    if runtime is None:
        raise HTTPException(503, {"code": "DATABASE_NOT_CONFIGURED", "message": "数据库尚未配置"})
    try:
        database_ready(runtime.engine)
        settings = get_settings()
        runtime.identities.initialize_allowlist_once(settings.admin_open_ids, datetime.utcnow())
    except Exception:
        raise HTTPException(503, {"code": "DATABASE_UNAVAILABLE", "message": "数据库不可用"})
    return {"data": {"database": "ready", "schema": "reachable"}, "meta": {}}


@app.get("/admin/auth/login")
def login(settings: Settings = Depends(get_settings), runtime=Depends(get_runtime)):
    if not settings.identity_ready:
        raise HTTPException(503, {"code": "IDENTITY_NOT_CONFIGURED", "message": "飞书登录尚未配置"})
    if runtime is None:
        raise HTTPException(503, {"code":"DATABASE_NOT_CONFIGURED","message":"数据库尚未配置"})
    from urllib.parse import urlencode
    from .feishu.oauth import OAuthService
    runtime.identities.initialize_allowlist_once(settings.admin_open_ids, datetime.utcnow())
    state=OAuthService(runtime.sessions,settings,None).begin()
    response=RedirectResponse('https://open.feishu.cn/open-apis/authen/v1/index?'+urlencode({'app_id':settings.feishu_app_id,'redirect_uri':settings.feishu_redirect_uri,'state':state}),status_code=302)
    response.set_cookie('org_oauth_state',state,max_age=600,httponly=True,secure=True,samesite='lax',path='/admin/auth')
    response.headers['Cache-Control']='no-store'
    return response


@app.get('/admin/auth/callback')
def oauth_callback(code: str | None = None, state: str | None = None, org_oauth_state: str | None = Cookie(default=None), settings=Depends(get_settings), runtime=Depends(get_runtime)):
    from .feishu.oauth import OAuthService
    from .feishu.client import FeishuClient
    if not settings.identity_ready or runtime is None:
        return error('IDENTITY_NOT_CONFIGURED','飞书登录尚未配置',503)
    try:
        if not code: raise ValueError('OAUTH_CODE_MISSING')
        session,csrf=OAuthService(runtime.sessions,settings,FeishuClient(settings.feishu_app_id,settings.feishu_app_secret.get_secret_value())).complete(state,org_oauth_state,code)
        response=RedirectResponse('/organization',status_code=302)
        response.set_cookie('org_session',session.id,max_age=43200,httponly=True,secure=True,samesite='lax')
        response.set_cookie('org_csrf',csrf,max_age=43200,httponly=True,secure=True,samesite='strict',path='/admin/auth')
    except ValueError as exc:
        response=error(str(exc) if str(exc) in {'OAUTH_CODE_MISSING','OAUTH_STATE_INVALID','OAUTH_IDENTITY_MISMATCH','ADMIN_NOT_ALLOWED','LOGIN_IDENTITY_MISMATCH','EMPLOYEE_INACTIVE'} else 'OAUTH_FAILED','登录校验失败，请重新发起登录',403)
    except RuntimeError as exc:
        response=error('CONFIG_BINDING_MISMATCH','当前应用或租户与数据库绑定不一致',503) if str(exc)=='CONFIG_BINDING_MISMATCH' else error('OAUTH_UPSTREAM_UNAVAILABLE','飞书登录暂时不可用',502)
    response.delete_cookie('org_oauth_state',path='/admin/auth',secure=True,httponly=True,samesite='lax')
    response.headers['Cache-Control']='no-store'
    return response


@app.get('/admin/auth/session')
def auth_session(org_csrf: str | None = Cookie(default=None), identity=Depends(get_admin_identity), settings=Depends(get_settings)):
    import hashlib, hmac
    secret=settings.session_secret.get_secret_value() if settings.session_secret else ''
    digest=hmac.new(secret.encode(),(org_csrf or '').encode(),hashlib.sha256).hexdigest()
    if not org_csrf or not hmac.compare_digest(digest,identity.csrf_hash):
        raise HTTPException(403,{'code':'CSRF_REQUIRED','message':'登录会话缺少有效 CSRF，请重新登录'})
    return JSONResponse({'data':{'open_id':identity.open_id,'csrf_token':org_csrf},'meta':{}},headers={'Cache-Control':'no-store'})


@app.post("/admin/auth/logout")
def logout(authorization=Depends(require_admin_write), runtime: Runtime | None = Depends(get_runtime)):
    identity, _ = authorization
    runtime.identities.revoke_session(identity.id, datetime.utcnow())
    response = JSONResponse({"data": {"revoked": True}, "meta": {}})
    response.delete_cookie("org_session", httponly=True, secure=True, samesite="lax")
    response.delete_cookie('org_csrf',path='/admin/auth',httponly=True,secure=True,samesite='strict')
    response.delete_cookie('org_oauth_state',path='/admin/auth',httponly=True,secure=True,samesite='lax')
    return response


@app.get("/api/v1/status")
def public_status(identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    data, meta = service.status()
    return {"data": data, "meta": meta}


def _list(method: str, service: ReadService, **filters):
    data, meta = getattr(service, method)(**filters)
    return {"data": data, "meta": meta}


@app.get("/api/v1/departments")
def departments(parent_id: str | None = None, root_id: str | None = None, include_descendants: bool = False, include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    return _list("list_departments", service, parent_id=parent_id, root_id=root_id, include_descendants=include_descendants, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)


@app.get("/api/v1/departments/{department_id}")
def department(department_id: str, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    data, meta = service.get_department(department_id)
    if data is None:
        raise HTTPException(404, {"code": "DEPARTMENT_NOT_FOUND", "message": "部门不存在"})
    return {"data": data, "meta": meta}


@app.get("/api/v1/employees")
def employees(department_id: str | None = None, include_descendants: bool = False, store_id: str | None = None, primary_store_id: str | None = None, include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    return _list("list_employees", service, department_id=department_id, include_descendants=include_descendants, store_id=store_id, primary_store_id=primary_store_id, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)


@app.get("/api/v1/employees/{employee_id}")
def employee(employee_id: str, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    data, meta = service.get_employee(employee_id)
    if data is None:
        raise HTTPException(404, {"code": "EMPLOYEE_NOT_FOUND", "message": "员工不存在"})
    return {"data": data, "meta": meta}


@app.get("/api/v1/stores")
def stores(include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    return _list("list_stores", service, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)


@app.get("/api/v1/stores/{store_id}")
def store(store_id: str, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    data, meta = service.get_store(store_id)
    if data is None:
        raise HTTPException(404, {"code": "STORE_NOT_FOUND", "message": "门店不存在"})
    return {"data": data, "meta": meta}


@app.get("/api/v1/stores/{store_id}/employees")
def store_employees(store_id: str, membership: str = Query("all", pattern="^(all|primary)$"), include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, dataset_epoch: str | None = None, data_version: int | None = None, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    return _list("list_store_employees", service, store_id=store_id, membership=membership, include_inactive=include_inactive, limit=limit, cursor=cursor, dataset_epoch=dataset_epoch, data_version=data_version)


class JobRequest(BaseModel):
    type: str
    root_department_id: str | None = None


@app.post("/admin/api/sync/jobs", status_code=202)
def submit_job(body: JobRequest, authorization=Depends(require_admin_write), runtime: Runtime | None = Depends(get_runtime)):
    from datetime import datetime, timezone
    if body.type not in {"full", "subtree", "reconcile"} or (body.type == "subtree" and not body.root_department_id):
        raise HTTPException(422, {"code": "INVALID_JOB_SCOPE", "message": "同步任务类型或范围无效"})
    identity, _ = authorization
    job, reused = runtime.jobs.submit(body.type, body.root_department_id, f"admin:{identity.open_id}", datetime.now(timezone.utc))
    return {"data": {"job_id": job.id, "status": job.status, "reused": reused}, "meta": {}}


@app.get("/admin/api/sync/jobs")
def list_jobs(limit: int = Query(100, ge=1, le=500), status: str | None = None, cursor: str | None = None, identity=Depends(get_admin_identity), runtime: Runtime | None = Depends(get_runtime)):
    from sqlalchemy import select
    from .persistence.models import SyncJob
    with runtime.sessions() as db:
        stmt = select(SyncJob).order_by(SyncJob.created_at.desc(), SyncJob.id.desc()).limit(limit)
        if status:
            stmt = stmt.where(SyncJob.status == status)
        if cursor:
            try:
                cursor_time, cursor_id = cursor.split("|", 1)
                boundary = datetime.fromisoformat(cursor_time)
            except ValueError:
                raise HTTPException(400, {"code": "INVALID_CURSOR", "message": "任务游标无效"})
            from sqlalchemy import or_, and_
            stmt = stmt.where(or_(SyncJob.created_at < boundary, and_(SyncJob.created_at == boundary, SyncJob.id < cursor_id)))
        rows = list(db.scalars(stmt.limit(limit + 1)))
        page = rows[:limit]
        from .web import utc_datetime
        next_cursor = f"{page[-1].created_at.isoformat()}|{page[-1].id}" if len(rows) > limit else None
        return {"data": [{"job_id": job.id, "type": job.type, "root_department_id": job.root_department_id, "status": job.status, "phase": job.phase, "attempt": job.attempt, "error_code": job.error_code, "created_at": utc_datetime(job.created_at), "updated_at": utc_datetime(job.updated_at)} for job in page], "meta": {"next_cursor": next_cursor}}


@app.get("/admin/api/sync/jobs/{job_id}")
def get_job(job_id: str, identity=Depends(get_admin_identity), runtime: Runtime | None = Depends(get_runtime)):
    from sqlalchemy.orm import Session
    from .persistence.models import SyncJob
    with runtime.sessions() as db:
        job = db.get(SyncJob, job_id)
        if job is None:
            raise HTTPException(404, {"code": "JOB_NOT_FOUND", "message": "同步任务不存在"})
        from .persistence.models import SystemSetting
        import json
        record=db.get(SystemSetting,'job_progress:'+job.id)
        progress=json.loads(record.value) if record else {'departments_processed':None,'employees_processed':None,'departments_total':None,'employees_total':None}
        return {"data": {"job_id": job.id, "type": job.type, "root_department_id": job.root_department_id, "status": job.status, "phase": job.phase, "attempt": job.attempt, "error_code": job.error_code,'progress':progress}, "meta": {}}


@app.post("/admin/api/sync/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, authorization=Depends(require_admin_write), runtime: Runtime | None = Depends(get_runtime)):
    from datetime import datetime, timezone
    identity, _ = authorization
    try:
        job = runtime.jobs.retry(job_id, f"admin:{identity.open_id}", datetime.now(timezone.utc))
    except ValueError:
        raise HTTPException(409, {"code": "JOB_NOT_RETRYABLE", "message": "任务不存在或当前状态不可重试"})
    return {"data": {"job_id": job.id, "status": job.status, "attempt": job.attempt}, "meta": {}}

```

## backend/app/persistence/__init__.py
```


```

## backend/app/persistence/database.py
```
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_mysql_engine(database_url: str) -> Engine:
    if not database_url.startswith("mysql+pymysql://"):
        raise ValueError("ORG_DATABASE_URL must use mysql+pymysql")
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1800, isolation_level="REPEATABLE READ", hide_parameters=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def database_ready(engine: Engine) -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return True

```

## backend/app/persistence/models.py
```
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


TABLE_ARGS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
SOURCE_ID = String(191, collation="utf8mb4_bin")


class Base(DeclarativeBase):
    pass


class OAuthState(Base):
    __tablename__ = "oauth_state"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = TABLE_ARGS


class LoginIdentity(Base):
    __tablename__ = "login_identity"
    open_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(SOURCE_ID)
    tenant_key: Mapped[str] = mapped_column(SOURCE_ID)
    __table_args__ = TABLE_ARGS


class WorkerLease(Base):
    __tablename__ = "worker_lease"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str | None] = mapped_column(SOURCE_ID)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = TABLE_ARGS


class PendingFact(Base):
    __tablename__ = 'pending_fact'
    object_type: Mapped[str] = mapped_column(String(32),primary_key=True)
    source_id: Mapped[str] = mapped_column(SOURCE_ID,primary_key=True)
    normalized_data: Mapped[dict] = mapped_column(JSON)
    error_code: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = TABLE_ARGS


class DatasetState(Base):
    __tablename__ = "dataset_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_epoch: Mapped[str] = mapped_column(SOURCE_ID)
    data_version: Mapped[int] = mapped_column(BigInteger, default=0)
    initialization_status: Mapped[str] = mapped_column(String(32), default="pending")
    coverage_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class SystemSetting(Base):
    __tablename__ = "system_setting"
    key: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    __table_args__ = TABLE_ARGS


class Department(Base):
    __tablename__ = "department"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    feishu_department_id: Mapped[str] = mapped_column(SOURCE_ID, unique=True)
    parent_id: Mapped[str | None] = mapped_column(SOURCE_ID, ForeignKey("department.id"))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")
    sync_quality: Mapped[str] = mapped_column(String(32), default="unknown")
    is_virtual_root: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class Employee(Base):
    __tablename__ = "employee"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    feishu_user_id: Mapped[str] = mapped_column(SOURCE_ID, unique=True)
    open_id: Mapped[str | None] = mapped_column(SOURCE_ID, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    employee_no: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")
    sync_quality: Mapped[str] = mapped_column(String(32), default="unknown")
    primary_department_id: Mapped[str | None] = mapped_column(SOURCE_ID, ForeignKey("department.id"))
    primary_store_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class EmployeeDepartment(Base):
    __tablename__ = "employee_department"
    employee_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("employee.id"), primary_key=True)
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = TABLE_ARGS


class StoreProfile(Base):
    __tablename__ = "store_profile"
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True)
    is_store: Mapped[bool] = mapped_column(Boolean, default=False)
    store_code: Mapped[str | None] = mapped_column(String(128, collation="utf8mb4_bin"), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = TABLE_ARGS


class StoreCodeReservation(Base):
    __tablename__ = "store_code_reservation"
    store_code: Mapped[str] = mapped_column(String(128, collation="utf8mb4_bin"), primary_key=True)
    department_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class EmployeeStore(Base):
    __tablename__ = "employee_store"
    employee_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("employee.id"), primary_key=True)
    store_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("department.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    path: Mapped[list] = mapped_column(JSON)
    __table_args__ = TABLE_ARGS


class FeishuConnection(Base):
    __tablename__ = "feishu_connection"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_key: Mapped[str | None] = mapped_column(SOURCE_ID, unique=True)
    app_id: Mapped[str] = mapped_column(SOURCE_ID)
    status: Mapped[str] = mapped_column(String(32))
    coverage_status: Mapped[str] = mapped_column(String(32), default="unknown")
    __table_args__ = TABLE_ARGS


class AdminAllowlist(Base):
    __tablename__ = "admin_allowlist"
    open_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class AdminSession(Base):
    __tablename__ = "admin_session"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    open_id: Mapped[str] = mapped_column(SOURCE_ID, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class ApiClient(Base):
    __tablename__ = "api_client"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    secret_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class SyncJob(Base):
    __tablename__ = "sync_job"
    id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    root_department_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    requested_by: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    phase: Mapped[str | None] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_sync_job_scope", "type", "root_department_id", "status"), TABLE_ARGS)


class EventInbox(Base):
    __tablename__ = "event_inbox"
    event_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    object_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = TABLE_ARGS


class SyncStaging(Base):
    __tablename__ = "sync_staging"
    job_id: Mapped[str] = mapped_column(SOURCE_ID, ForeignKey("sync_job.id"), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_id: Mapped[str] = mapped_column(SOURCE_ID, primary_key=True)
    normalized_data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = TABLE_ARGS


class ChangeLog(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(SOURCE_ID)
    source: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(255))
    job_id: Mapped[str | None] = mapped_column(SOURCE_ID)
    before_data: Mapped[dict | None] = mapped_column(JSON)
    after_data: Mapped[dict | None] = mapped_column(JSON)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = TABLE_ARGS

```

## backend/app/persistence/read_service.py
```
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.services import ReadService
from app.public_api.cursor import CursorCodec, DatasetChanged, InvalidCursor
from app.web import utc_datetime

from .models import DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreProfile


class SqlReadService(ReadService):
    def __init__(self, sessions: sessionmaker[Session], cursor_secret: str):
        self._sessions = sessions
        self._cursors = CursorCodec(cursor_secret)

    def _state(self, db: Session) -> DatasetState:
        state = db.get(DatasetState, 1)
        if state is None or state.initialization_status != "complete":
            raise RuntimeError("INITIALIZATION_INCOMPLETE")
        return state

    @staticmethod
    def _meta(state: DatasetState, next_cursor: str | None = None) -> dict:
        return {
            "dataset_epoch": state.dataset_epoch,
            "data_version": state.data_version,
            "coverage_status": state.coverage_status,
            "last_full_sync_at": utc_datetime(state.last_full_sync_at),
            "next_cursor": next_cursor,
        }

    def status(self):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            return ({"initialization_status": state.initialization_status, "coverage_status": state.coverage_status}, self._meta(state))

    def list_departments(self, **filters):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            self._check_version(state, filters)
            stmt = select(Department).order_by(Department.id).limit(filters.get("limit", 100) + 1)
            if not filters.get("include_inactive"):
                stmt = stmt.where(Department.status == "active")
            if filters.get("parent_id") is not None:
                stmt = stmt.where(Department.parent_id == filters["parent_id"])
            if filters.get("root_id") is not None:
                if filters.get("include_descendants"):
                    tree = select(Department.id).where(Department.id == filters["root_id"]).cte("department_tree", recursive=True)
                    tree = tree.union_all(select(Department.id).join(tree, Department.parent_id == tree.c.id))
                    stmt = stmt.where(Department.id.in_(select(tree.c.id)))
                else:
                    stmt = stmt.where(Department.id == filters["root_id"])
            last_id = self._last_id(state, "departments", filters)
            if last_id:
                stmt = stmt.where(Department.id > last_id)
            rows = list(db.scalars(stmt))
            page, next_cursor = self._page(rows, filters.get("limit", 100))
            return ([self._department(db, row) for row in page], self._meta(state, self._next_cursor(state, "departments", filters, next_cursor)))

    def get_department(self, department_id: str):
        with self._sessions() as db, db.begin():
            state, row = self._state(db), db.get(Department, department_id)
            return (self._department(db, row) if row else None, self._meta(state))

    def list_employees(self, **filters):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            self._check_version(state, filters)
            stmt = select(Employee).distinct().order_by(Employee.id).limit(filters.get("limit", 100) + 1)
            if not filters.get("include_inactive"):
                stmt = stmt.where(Employee.status == "active")
            if filters.get("department_id"):
                department_ids = select(EmployeeDepartment.employee_id).where(EmployeeDepartment.active.is_(True))
                if filters.get("include_descendants"):
                    tree = select(Department.id).where(Department.id == filters["department_id"]).cte("employee_department_tree", recursive=True)
                    tree = tree.union_all(select(Department.id).join(tree, Department.parent_id == tree.c.id))
                    department_ids = department_ids.where(EmployeeDepartment.department_id.in_(select(tree.c.id)))
                else:
                    department_ids = department_ids.where(EmployeeDepartment.department_id == filters["department_id"])
                stmt = stmt.where(Employee.id.in_(department_ids))
            if filters.get("store_id"):
                stmt = stmt.where(Employee.id.in_(select(EmployeeStore.employee_id).where(EmployeeStore.store_id == filters["store_id"])))
            if filters.get("primary_store_id"):
                stmt = stmt.where(Employee.id.in_(select(EmployeeStore.employee_id).where(EmployeeStore.store_id == filters["primary_store_id"], EmployeeStore.is_primary.is_(True))))
            last_id = self._last_id(state, "employees", filters)
            if last_id:
                stmt = stmt.where(Employee.id > last_id)
            rows = list(db.scalars(stmt))
            page, next_cursor = self._page(rows, filters.get("limit", 100))
            return ([self._employee(db, row) for row in page], self._meta(state, self._next_cursor(state, "employees", filters, next_cursor)))

    def get_employee(self, employee_id: str):
        with self._sessions() as db, db.begin():
            state, row = self._state(db), db.get(Employee, employee_id)
            return (self._employee(db, row) if row else None, self._meta(state))

    def list_stores(self, **filters):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            self._check_version(state, filters)
            stmt = select(StoreProfile, Department).join(Department).where(StoreProfile.is_store.is_(True)).order_by(StoreProfile.department_id).limit(filters.get("limit", 100) + 1)
            if not filters.get("include_inactive"):
                stmt = stmt.where(Department.status == "active")
            last_id = self._last_id(state, "stores", filters)
            if last_id:
                stmt = stmt.where(StoreProfile.department_id > last_id)
            rows = list(db.execute(stmt))
            page, next_cursor = self._page(rows, filters.get("limit", 100), key=lambda row: row[0].department_id)
            return ([self._store(db, *row) for row in page], self._meta(state, self._next_cursor(state, "stores", filters, next_cursor)))

    def get_store(self, store_id: str):
        with self._sessions() as db, db.begin():
            state = self._state(db)
            row = db.execute(select(StoreProfile, Department).join(Department).where(StoreProfile.department_id == store_id)).one_or_none()
            return (self._store(db, *row) if row else None, self._meta(state))

    def list_store_employees(self, store_id: str, **filters):
        filters["store_id"] = store_id
        if filters.pop("membership", "all") == "primary":
            filters["primary_store_id"] = store_id
            filters.pop("store_id")
        return self.list_employees(**filters)

    @staticmethod
    def _check_version(state: DatasetState, filters: dict) -> None:
        if filters.get("dataset_epoch") not in (None, state.dataset_epoch) or filters.get("data_version") not in (None, state.data_version):
            raise RuntimeError("DATASET_CHANGED")

    @staticmethod
    def _bound_filters(resource: str, filters: dict) -> dict:
        return {"resource": resource, **{key: value for key, value in filters.items() if key not in {"cursor", "dataset_epoch", "data_version"}}}

    def _last_id(self, state: DatasetState, resource: str, filters: dict) -> str | None:
        cursor = filters.get("cursor")
        if not cursor:
            return None
        try:
            return self._cursors.decode(cursor, epoch=state.dataset_epoch, version=state.data_version, filters=self._bound_filters(resource, filters)).last_id
        except DatasetChanged as exc:
            raise RuntimeError("DATASET_CHANGED") from exc
        except InvalidCursor as exc:
            raise RuntimeError("INVALID_CURSOR") from exc

    def _next_cursor(self, state: DatasetState, resource: str, filters: dict, last_id: str | None) -> str | None:
        if last_id is None:
            return None
        return self._cursors.encode(epoch=state.dataset_epoch, version=state.data_version, filters=self._bound_filters(resource, filters), last_id=last_id)

    @staticmethod
    def _page(rows: list, limit: int, key=lambda row: row.id):
        has_more = len(rows) > limit
        page = rows[:limit]
        return page, key(page[-1]) if has_more and page else None

    @staticmethod
    def _department(db: Session, row: Department) -> dict:
        profile = db.get(StoreProfile, row.id)
        names, current, visited = [], row, set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            names.append(current.name)
            current = db.get(Department, current.parent_id) if current.parent_id else None
        return {"id": row.id, "parent_id": row.parent_id, "name": row.name, "path": list(reversed(names)), "status": row.status, "sync_quality": row.sync_quality, "is_virtual_root": row.is_virtual_root, "is_store": bool(profile and profile.is_store), "store_code": profile.store_code if profile else None, "notes": profile.notes if profile else None}

    @staticmethod
    def _store(db: Session, profile: StoreProfile, department: Department) -> dict:
        names, current, visited = [], department, set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            names.append(current.name)
            current = db.get(Department, current.parent_id) if current.parent_id else None
        employee_count = db.scalar(select(func.count(func.distinct(EmployeeStore.employee_id))).where(EmployeeStore.store_id == department.id)) or 0
        primary_count = db.scalar(select(func.count(func.distinct(EmployeeStore.employee_id))).where(EmployeeStore.store_id == department.id, EmployeeStore.is_primary.is_(True))) or 0
        return {"id": department.id, "department_id": department.id, "name": department.name, "path": list(reversed(names)), "status": department.status, "is_store": profile.is_store, "store_code": profile.store_code, "notes": profile.notes, "employee_count": employee_count, "primary_employee_count": primary_count}

    @staticmethod
    def _employee(db: Session, row: Employee) -> dict:
        memberships = list(db.scalars(select(EmployeeDepartment.department_id).where(EmployeeDepartment.employee_id == row.id, EmployeeDepartment.active.is_(True))))
        stores = list(db.execute(select(EmployeeStore.store_id, EmployeeStore.is_primary).where(EmployeeStore.employee_id == row.id)))
        primary_store = next((store_id for store_id, primary in stores if primary), None)
        department_details = [SqlReadService._department(db, db.get(Department, identifier)) for identifier in memberships]
        store_details = []
        for relation in db.scalars(select(EmployeeStore).where(EmployeeStore.employee_id==row.id)):
            department=db.get(Department,relation.store_id)
            store_details.append({'id':relation.store_id,'name':department.name,'is_primary':relation.is_primary,'path':relation.path,'path_names':[db.get(Department,identifier).name for identifier in relation.path]})
        return {"id": row.id, "name": row.name, "employee_no": row.employee_no, "status": row.status, "sync_quality": row.sync_quality, "department_ids": memberships, "departments":department_details,"stores":store_details,"primary_department_id": row.primary_department_id, "store_ids": [item[0] for item in stores], "primary_store_id": primary_store, "primary_store_status": row.primary_store_status}

```

## backend/app/persistence/repositories.py
```
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, DatasetState, SyncJob, SystemSetting, LoginIdentity, Employee


class SqlIdentityRepository:
    """每次认证均读取数据库，使撤销与白名单修改立即生效。"""

    def __init__(self, sessions: sessionmaker[Session], pepper: str):
        self._sessions = sessions
        self._pepper = pepper.encode()

    def authenticate_api_key(self, client_id: str, secret: str) -> ApiClient | None:
        with self._sessions() as db:
            record = db.get(ApiClient, client_id)
            if record is None or record.revoked_at is not None:
                return None
            return record if hmac.compare_digest(record.secret_hash, self._hash(secret)) else None

    def authenticate_session(self, session_id: str, now: datetime) -> AdminSession | None:
        with self._sessions() as db:
            return db.scalar(self.session_auth_statement(session_id, now))

    @staticmethod
    def session_auth_statement(session_id: str, now: datetime):
        inactive = select(LoginIdentity.open_id).join(Employee,Employee.feishu_user_id==LoginIdentity.user_id).where(LoginIdentity.open_id==AdminSession.open_id,Employee.status=='inactive').exists()
        return select(AdminSession).join(
            AdminAllowlist, AdminAllowlist.open_id == AdminSession.open_id
        ).where(AdminSession.id == session_id, AdminSession.revoked_at.is_(None), AdminSession.expires_at > now, ~inactive)

    def create_session(self, open_id: str, csrf_token: str, expires_at: datetime, now: datetime) -> AdminSession | None:
        """供 OAuth 适配器在换取并核实 open_id 后建立可撤销会话。"""
        with self._sessions.begin() as db:
            if db.get(AdminAllowlist, open_id) is None:
                return None
            record = AdminSession(id=secrets.token_urlsafe(32), open_id=open_id, csrf_hash=self._hmac(csrf_token), expires_at=expires_at)
            db.add(record)
            return record

    def revoke_session(self, session_id: str, now: datetime) -> bool:
        with self._sessions.begin() as db:
            record = db.get(AdminSession, session_id)
            if record is None:
                return False
            record.revoked_at = now
            return True

    def initialize_allowlist_once(self, open_ids: set[str], now: datetime) -> bool:
        """仅首次初始化配置白名单；持久标记防止重启恢复已删除管理员。"""
        with self._sessions.begin() as db:
            marker = db.scalar(select(SystemSetting).where(SystemSetting.key == "admin_allowlist_initialized").with_for_update())
            if marker is not None:
                return False
            for open_id in open_ids:
                db.add(AdminAllowlist(open_id=open_id, created_at=now))
            db.add(SystemSetting(key="admin_allowlist_initialized", value="true"))
            return True

    def issue_api_key(self, name: str, now: datetime) -> tuple[ApiClient, str]:
        secret = secrets.token_urlsafe(32)
        record = ApiClient(id=secrets.token_urlsafe(12), name=name.strip(), secret_hash=self._hash(secret), created_at=now)
        with self._sessions.begin() as db:
            db.add(record)
        return record, secret

    def revoke_api_key(self, client_id: str, now: datetime) -> bool:
        with self._sessions.begin() as db:
            record = db.get(ApiClient, client_id)
            if record is None:
                return False
            record.revoked_at = now
        return True

    def create_api_key(self, name: str, actor: str, now: datetime) -> tuple[ApiClient, str]:
        secret = secrets.token_urlsafe(32)
        record = ApiClient(id=secrets.token_urlsafe(12), name=name, secret_hash=self._hash(secret), created_at=now)
        with self._sessions.begin() as db:
            db.add(record)
            db.add(ChangeLog(object_type="api_client", object_id=record.id, source="admin", actor=actor, before_data=None, after_data={"name": name, "revoked": False}, committed_at=now))
        return record, secret

    def rotate_api_key(self, client_id: str, actor: str, now: datetime) -> tuple[ApiClient, str] | None:
        secret = secrets.token_urlsafe(32)
        with self._sessions.begin() as db:
            previous = db.scalar(select(ApiClient).where(ApiClient.id == client_id).with_for_update())
            if previous is None or previous.revoked_at is not None:
                return None
            replacement = ApiClient(id=secrets.token_urlsafe(12), name=previous.name, secret_hash=self._hash(secret), created_at=now)
            previous.revoked_at = now
            db.add(replacement)
            db.add(ChangeLog(object_type="api_client", object_id=client_id, source="admin", actor=actor, before_data={"name": previous.name, "revoked": False}, after_data={"name": previous.name, "revoked": True, "replacement_client_id": replacement.id}, committed_at=now))
            return replacement, secret

    def revoke_api_key_audited(self, client_id: str, actor: str, now: datetime) -> bool:
        with self._sessions.begin() as db:
            record = db.scalar(select(ApiClient).where(ApiClient.id == client_id).with_for_update())
            if record is None:
                return False
            if record.revoked_at is None:
                record.revoked_at = now
                db.add(ChangeLog(object_type="api_client", object_id=client_id, source="admin", actor=actor, before_data={"name": record.name, "revoked": False}, after_data={"name": record.name, "revoked": True}, committed_at=now))
            return True

    def add_admin(self, open_id: str, actor: str, now: datetime) -> bool:
        with self._sessions.begin() as db:
            if db.get(AdminAllowlist, open_id) is not None:
                return False
            db.add(AdminAllowlist(open_id=open_id, created_at=now))
            db.add(ChangeLog(object_type="admin_allowlist", object_id=open_id, source="admin", actor=actor, before_data=None, after_data={"enabled": True}, committed_at=now))
            return True

    def remove_admin(self, open_id: str, actor: str, now: datetime) -> bool:
        with self._sessions.begin() as db:
            record = db.scalar(select(AdminAllowlist).where(AdminAllowlist.open_id == open_id).with_for_update())
            if record is None:
                return False
            db.query(AdminSession).filter(AdminSession.open_id == open_id, AdminSession.revoked_at.is_(None)).update({AdminSession.revoked_at: now}, synchronize_session=False)
            db.add(ChangeLog(object_type="admin_allowlist", object_id=open_id, source="admin", actor=actor, before_data={"enabled": True}, after_data={"enabled": False}, committed_at=now))
            db.delete(record)
            return True

    def _hash(self, secret: str) -> str:
        return hashlib.scrypt(secret.encode(), salt=hashlib.sha256(self._pepper).digest(), n=2**14, r=8, p=1).hex()

    def _hmac(self, value: str) -> str:
        return hmac.new(self._pepper, value.encode(), hashlib.sha256).hexdigest()


class SqlSyncJobRepository:
    """使用 MySQL 行锁实现任务复用、认领和重试。"""

    ACTIVE = ("queued", "running")

    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def submit(self, job_type: str, root_department_id: str | None, requested_by: str, now: datetime) -> tuple[SyncJob, bool]:
        with self._sessions.begin() as db:
            lock_row = db.scalar(select(SystemSetting).where(SystemSetting.key == "task_queue_lock").with_for_update())
            if lock_row is None:
                raise RuntimeError("DATABASE_SCHEMA_INCOMPLETE")
            existing = db.scalar(
                select(SyncJob).where(
                    SyncJob.type == job_type,
                    SyncJob.root_department_id.is_(None) if root_department_id is None else SyncJob.root_department_id == root_department_id,
                    SyncJob.status.in_(self.ACTIVE),
                ).with_for_update()
            )
            if existing is not None:
                return existing, True
            job = SyncJob(
                id=secrets.token_urlsafe(12), type=job_type, root_department_id=root_department_id,
                requested_by=requested_by, status="queued", attempt=1, lease_generation=0,
                created_at=now, updated_at=now,
            )
            db.add(job)
            return job, False

    def claim_next(self, now: datetime, lease_expires_at: datetime) -> SyncJob | None:
        with self._sessions.begin() as db:
            job = db.scalar(
                select(SyncJob).where(SyncJob.status == "queued", or_(SyncJob.lease_expires_at.is_(None), SyncJob.lease_expires_at <= now)).order_by(SyncJob.created_at, SyncJob.id).limit(1).with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            job.status = "running"
            job.lease_generation += 1
            job.lease_expires_at = lease_expires_at
            job.updated_at = now
            return job

    def mark_succeeded(self, job_id: str, lease_generation: int, now: datetime) -> SyncJob:
        return self._finish(job_id, lease_generation, "succeeded", None, None, now)

    def mark_failed(self, job_id: str, lease_generation: int, error_code: str, error_detail: str, now: datetime) -> SyncJob:
        return self._finish(job_id, lease_generation, "failed", error_code, error_detail, now)

    def _finish(self, job_id: str, lease_generation: int, status: str, error_code: str | None, error_detail: str | None, now: datetime) -> SyncJob:
        with self._sessions.begin() as db:
            job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update())
            if job is None or job.status != "running" or job.lease_generation != lease_generation:
                raise ValueError("job lease is stale")
            job.status, job.error_code, job.error_detail = status, error_code, error_detail
            job.lease_expires_at, job.updated_at = None, now
            return job

    def retry(self, job_id: str, requested_by: str, now: datetime) -> SyncJob:
        with self._sessions.begin() as db:
            job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update())
            if job is None or job.status != "failed":
                raise ValueError("only failed jobs can be retried")
            job.status, job.requested_by, job.attempt = "queued", requested_by, job.attempt + 1
            job.error_code = job.error_detail = None
            job.updated_at = now
            return job

```

## backend/app/public_api/__init__.py
```


```

## backend/app/public_api/cursor.py
```
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass


class InvalidCursor(ValueError):
    pass


class DatasetChanged(ValueError):
    pass


@dataclass(frozen=True)
class CursorPage:
    last_id: str


class CursorCodec:
    def __init__(self, secret: str):
        self._secret = secret.encode()

    def encode(self, *, epoch: str, version: int, filters: dict, last_id: str) -> str:
        payload = {"epoch": epoch, "version": version, "filters": filters, "last_id": last_id}
        raw = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode()
        signature = hmac.new(self._secret, raw.encode(), hashlib.sha256).hexdigest()
        return f"{raw}.{signature}"

    def decode(self, cursor: str, *, epoch: str, version: int, filters: dict) -> CursorPage:
        try:
            raw, signature = cursor.split(".", 1)
            expected = hmac.new(self._secret, raw.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCursor("cursor signature is invalid")
            payload = json.loads(base64.urlsafe_b64decode(raw))
        except (ValueError, json.JSONDecodeError) as exc:
            raise InvalidCursor("cursor is malformed") from exc
        if payload["epoch"] != epoch or payload["version"] != version:
            raise DatasetChanged("dataset changed during pagination")
        if payload["filters"] != filters:
            raise InvalidCursor("cursor does not match filters")
        return CursorPage(payload["last_id"])


```

## backend/app/services.py
```
from typing import Protocol


class ReadService(Protocol):
    """公开查询边界；数据库实现需在一次一致读事务中返回 data 与 meta。"""

    def status(self) -> tuple[dict, dict]: ...
    def list_departments(self, **filters) -> tuple[list[dict], dict]: ...
    def get_department(self, department_id: str) -> tuple[dict | None, dict]: ...
    def list_employees(self, **filters) -> tuple[list[dict], dict]: ...
    def get_employee(self, employee_id: str) -> tuple[dict | None, dict]: ...
    def list_stores(self, **filters) -> tuple[list[dict], dict]: ...
    def get_store(self, store_id: str) -> tuple[dict | None, dict]: ...
    def list_store_employees(self, store_id: str, **filters) -> tuple[list[dict], dict]: ...


class UninitializedReadService:
    def _unavailable(self):
        raise RuntimeError("INITIALIZATION_INCOMPLETE")

    status = list_departments = get_department = list_employees = get_employee = list_stores = get_store = list_store_employees = _unavailable


```

## backend/app/stores/__init__.py
```
from .domain import StorePatch, validate_store_changes

__all__ = ["StorePatch", "validate_store_changes"]


```

## backend/app/stores/domain.py
```
from dataclasses import dataclass, replace


UNSET = object()


@dataclass(frozen=True)
class StorePatch:
    department_id: str
    is_store: bool
    store_code: str | None | object = UNSET
    notes: str | None | object = UNSET


@dataclass(frozen=True)
class StoreValidationError:
    department_id: str
    code: str
    message: str


class InvalidStoreChanges(ValueError):
    def __init__(self, errors: list[StoreValidationError]):
        self.errors = errors
        super().__init__("invalid store changes")


def validate_store_changes(changes: list[StorePatch], *, departments: dict[str, dict], raise_errors: bool = True):
    normalized: list[StorePatch] = []
    errors: list[StoreValidationError] = []
    seen_codes: set[str] = set()
    for change in changes:
        department = departments.get(change.department_id)
        code = change.store_code
        if code is not UNSET:
            code = code.strip() if code and code.strip() else None
        item = replace(change, store_code=code)
        if department is None:
            errors.append(StoreValidationError(change.department_id, "DEPARTMENT_NOT_FOUND", "部门不存在"))
        elif change.is_store and department["is_virtual_root"]:
            errors.append(StoreValidationError(change.department_id, "VIRTUAL_ROOT", "虚拟根不能设为门店"))
        elif change.is_store and department["status"] != "active":
            errors.append(StoreValidationError(change.department_id, "DEPARTMENT_INACTIVE", "失效部门不能新设为门店"))
        elif code is not UNSET and code is not None and code in seen_codes:
            errors.append(StoreValidationError(change.department_id, "DUPLICATE_STORE_CODE", "批次内门店编码重复"))
        else:
            if code is not UNSET and code is not None:
                seen_codes.add(code)
            normalized.append(item)
    if errors and raise_errors:
        raise InvalidStoreChanges(errors)
    return errors if errors else normalized


def merge_store_patch(current: dict, patch: StorePatch) -> dict:
    if not patch.is_store:
        return {**current, "is_store": False}
    return {
        "is_store": True,
        "store_code": current.get("store_code") if patch.store_code is UNSET else patch.store_code,
        "notes": current.get("notes") if patch.notes is UNSET else patch.notes,
    }

```

## backend/app/stores/service.py
```
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.directory.domain import Department as DomainDepartment
from app.directory.domain import Employee as DomainEmployee
from app.directory.domain import Membership, resolve_employee_stores
from app.persistence.models import ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreCodeReservation, StoreProfile

from .domain import InvalidStoreChanges, StorePatch, StoreValidationError, merge_store_patch, validate_store_changes


class StoreAdminService:
    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def preview(self, changes: list[StorePatch], expected_version: int) -> dict:
        with self._sessions() as db, db.begin():
            state = self._lock_state(db, expected_version, lock=False)
            normalized = self._validate(db, changes)
            before_projection = self._projection(db)
            after_projection = self._projection(db, {c.department_id: c.is_store for c in normalized})
            affected = sum(before_projection[key] != value for key, value in after_projection.items())
            concrete = []
            for change in normalized:
                after = merge_store_patch(self._snapshot(db.get(StoreProfile, change.department_id)), change)
                concrete.append({"department_id": change.department_id, **after})
            return {"data_version": state.data_version, "changes": concrete, "affected_employee_count": affected}

    def apply(self, changes: list[StorePatch], expected_version: int, actor: str, now: datetime) -> dict:
        with self._sessions.begin() as db:
            state = self._lock_state(db, expected_version, lock=True)
            normalized = self._validate(db, changes)
            business_changes = 0
            for change in normalized:
                current = db.get(StoreProfile, change.department_id)
                before = self._snapshot(current)
                after = merge_store_patch(before, change)
                if before == after:
                    continue
                if after["store_code"]:
                    reservation = db.get(StoreCodeReservation, after["store_code"])
                    if reservation and reservation.department_id != change.department_id:
                        raise InvalidStoreChanges([StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留")])
                    if reservation is None:
                        db.add(StoreCodeReservation(store_code=after["store_code"], department_id=change.department_id, reserved_at=now))
                if current is None:
                    current = StoreProfile(department_id=change.department_id)
                    db.add(current)
                current.is_store, current.store_code, current.notes = after["is_store"], after["store_code"], after["notes"]
                db.add(ChangeLog(object_type="store", object_id=change.department_id, source="admin", actor=actor, before_data=before, after_data=after, committed_at=now))
                business_changes += 1
            if business_changes:
                db.flush()
                self._rebuild_projection(db)
                state.data_version += 1
            return {"data_version": state.data_version, "changed_count": business_changes}

    def _validate(self, db: Session, changes: list[StorePatch]) -> list[StorePatch]:
        ids = [change.department_id for change in changes]
        departments = {row.id: {"status": row.status, "is_virtual_root": row.is_virtual_root} for row in db.scalars(select(Department).where(Department.id.in_(ids)))}
        normalized = validate_store_changes(changes, departments=departments)
        errors = []
        for change in normalized:
            current = self._snapshot(db.get(StoreProfile, change.department_id))
            code = merge_store_patch(current, change)["store_code"]
            reservation = db.get(StoreCodeReservation, code) if code else None
            if reservation is not None and reservation.department_id != change.department_id:
                errors.append(StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留"))
        if errors:
            raise InvalidStoreChanges(errors)
        return normalized

    @staticmethod
    def _lock_state(db: Session, expected_version: int, lock: bool) -> DatasetState:
        stmt = select(DatasetState).where(DatasetState.id == 1)
        state = db.scalar(stmt.with_for_update() if lock else stmt)
        if state is None:
            raise RuntimeError("INITIALIZATION_INCOMPLETE")
        if state.data_version != expected_version:
            raise RuntimeError("DATASET_CHANGED")
        return state

    @staticmethod
    def _snapshot(profile: StoreProfile | None) -> dict:
        return {"is_store": bool(profile and profile.is_store), "store_code": profile.store_code if profile else None, "notes": profile.notes if profile else None}

    @staticmethod
    def _projection(db, overrides=None):
        store_ids = set(db.scalars(select(StoreProfile.department_id).where(StoreProfile.is_store.is_(True))))
        for identifier, enabled in (overrides or {}).items():
            if enabled:
                store_ids.add(identifier)
            else:
                store_ids.discard(identifier)
        departments = {row.id: DomainDepartment(row.id, row.parent_id, row.id in store_ids, row.status, row.sync_quality) for row in db.scalars(select(Department))}
        relations = list(db.scalars(select(EmployeeDepartment)))
        by_employee: dict[str, list[Membership]] = {}
        for relation in relations:
            by_employee.setdefault(relation.employee_id, []).append(Membership(relation.employee_id, relation.department_id, relation.active))
        projection = {}
        for employee in db.scalars(select(Employee)):
            memberships = by_employee.get(employee.id, [])
            result = resolve_employee_stores(DomainEmployee(employee.id, employee.status, employee.primary_department_id, employee.sync_quality), memberships, departments)
            paths = {}
            for relation in memberships:
                if not relation.active:
                    continue
                path, current, visited = [], relation.department_id, set()
                while current is not None and current not in visited:
                    visited.add(current)
                    department = departments.get(current)
                    if department is None or department.sync_quality in {'unknown', 'pending_verification', 'inconsistent'}:
                        break
                    path.append(current)
                    if current in result.store_ids:
                        if current not in paths or relation.department_id == employee.primary_department_id:
                            paths[current] = path
                        break
                    current = department.parent_id
            projection[employee.id] = (result, paths)
        return projection

    @staticmethod
    def _rebuild_projection(db: Session) -> None:
        projection = StoreAdminService._projection(db)
        db.execute(delete(EmployeeStore))
        for employee in db.scalars(select(Employee)):
            result, paths = projection[employee.id]
            employee.primary_store_status = result.primary_store_status
            for store_id in result.store_ids:
                db.add(EmployeeStore(employee_id=employee.id, store_id=store_id, is_primary=store_id == result.primary_store_id, path=paths.get(store_id, [])))

```

## backend/app/sync/__init__.py
```
from .services import JobService, SyncJob

__all__ = ["JobService", "SyncJob"]


```

## backend/app/sync/collector.py
```
"""完整采集候选；分页异常向上抛出，绝不返回半轮结果。"""
from dataclasses import dataclass, field
from datetime import datetime,timezone


@dataclass
class Candidate:
    departments: dict = field(default_factory=dict)
    employees: dict = field(default_factory=dict)
    pending: list = field(default_factory=list)
    coverage_status: str = "unknown"
    full: bool = False
    collection_started_at: str | None = None


def normalize_user(raw):
    if not isinstance(raw.get('department_ids'),list) or any(not isinstance(d,str) or not d for d in raw['department_ids']):
        raise RuntimeError('FEISHU_MEMBERSHIP_UNREADABLE')
    status=raw.get('status')
    if not isinstance(status,dict) or not any(type(status.get(key)) is bool for key in ('is_resigned','is_exited')):
        raise RuntimeError('FEISHU_STATUS_UNREADABLE')
    identifier = raw["user_id"]
    departments = list(dict.fromkeys(raw.get("department_ids") or []))
    primaries = {order["department_id"] for order in raw.get("orders", []) if order.get("is_primary_dept") is True and order.get("department_id")}
    primary = next(iter(primaries)) if len(primaries) == 1 else None
    inconsistent = len(primaries) > 1 or (primary is not None and primary not in departments)
    return {"id": identifier, "feishu_user_id": identifier, "open_id": raw.get("open_id"), "name": raw["name"], "employee_no": raw.get("employee_no"), "status": "inactive" if raw.get("status", {}).get("is_resigned") is True or raw.get("status", {}).get("is_exited") is True else "active", "primary_department_id": primary if not inconsistent else None, "sync_quality": "inconsistent" if inconsistent else "complete", "department_ids": departments}


def normalize_department(raw):
    if not isinstance(raw.get('parent_department_id'),str) or not raw['parent_department_id']:
        raise RuntimeError('FEISHU_PARENT_UNREADABLE')
    if not isinstance(raw.get('status'),dict) or type(raw['status'].get('is_deleted')) is not bool:
        raise RuntimeError('FEISHU_STATUS_UNREADABLE')
    identifier = raw["open_department_id"]
    return {"id": identifier, "feishu_department_id": identifier, "parent_id": raw.get("parent_department_id") or "0", "name": raw["name"], "status": "inactive" if raw.get("status", {}).get("is_deleted") is True else "active", "sync_quality": "complete", "is_virtual_root": False}


class Collector:
    def __init__(self, api, coverage_verified=False, progress=None):
        self.api, self.coverage_verified = api, coverage_verified
        self.progress=progress

    def _progress(self,phase,result):
        if self.progress:
            self.progress(phase=phase,departments_processed=len(result.departments),employees_processed=len(result.employees),departments_total=None,employees_total=None)

    def collect(self, root=None, previous_departments=(), previous_users=()):
        result = Candidate(full=root is None,collection_started_at=datetime.now(timezone.utc).isoformat())
        result.departments["0"] = {"id": "0", "feishu_department_id": "0", "parent_id": None, "name": "组织", "status": "active", "sync_quality": "complete", "is_virtual_root": True}
        users, roots, groups = set(), [], []
        self._progress('scopes',result)
        for page in self.api.pages("scopes"):
            roots.extend(page.get("department_ids", []))
            users.update(page.get("user_ids", []))
            groups.extend(page.get("group_ids", []))
        if root: users.clear()
        users.update(previous_users)
        queue = [root] if root else list(dict.fromkeys(["0", *roots]))
        visited = set()
        while queue:
            identifier = queue.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            if identifier != "0":
                result.departments[identifier] = normalize_department(self.api.detail("department", identifier))
            for page in self.api.pages("children", department_id=identifier):
                queue.extend(item["open_department_id"] for item in page.get("items", []))
            for page in self.api.pages("users", department_id=identifier):
                users.update(item["user_id"] for item in page.get("items", []))
            self._progress('departments',result)
        for identifier in set(previous_departments)-set(result.departments)-{'0'}:
            try:
                result.departments[identifier]=normalize_department(self.api.detail('department',identifier))
            except RuntimeError:
                result.pending.append(('department',identifier))
        for identifier in sorted(users):
            self._user(result, identifier)
            self._progress('employees',result)
        self._ancestors(result)
        self._progress('collected',result)
        result.coverage_status = "complete" if self.coverage_verified and not groups and not result.pending and root is None else "incomplete" if groups or result.pending else "unknown"
        return result

    def _user(self, result, identifier):
        try:
            result.employees[identifier] = normalize_user(self.api.detail("user", identifier))
        except RuntimeError:
            result.pending.append(("employee", identifier))

    def _ancestors(self, result):
        queue = [d["parent_id"] for d in result.departments.values() if d["parent_id"]]
        queue.extend(d for u in result.employees.values() for d in u["department_ids"])
        visited = set(result.departments)
        while queue:
            identifier = queue.pop()
            if identifier in visited:
                continue
            visited.add(identifier)
            if identifier == '0':
                result.departments['0'] = {'id':'0','feishu_department_id':'0','parent_id':None,'name':'组织','status':'active','sync_quality':'complete','is_virtual_root':True}
                continue
            try:
                department = normalize_department(self.api.detail("department", identifier))
                result.departments[identifier] = department
                if department["parent_id"]:
                    queue.append(department["parent_id"])
            except RuntimeError:
                result.pending.append(("department", identifier))

    def event(self, event_type, identifier):
        result = Candidate()
        if ".user." in event_type:
            self._user(result, identifier)
        else:
            try:
                result.departments[identifier] = normalize_department(self.api.detail("department", identifier))
            except RuntimeError:
                result.pending.append(("department", identifier))
        self._ancestors(result)
        return result

```

## backend/app/sync/coverage.py
```
"""受运维主机权限约束的覆盖重新验收 CLI；不直接发布 complete。"""
import argparse
import json
import secrets
from datetime import datetime,timezone
from sqlalchemy import select,delete
from app.persistence.models import SystemSetting,DatasetState,SyncJob,ChangeLog


class CoverageService:
    def __init__(self,sessions): self.sessions=sessions

    def get(self):
        with self.sessions() as db:
            row=db.get(SystemSetting,'coverage_acceptance')
            return json.loads(row.value) if row else None

    def verified(self,fallback=False):
        with self.sessions() as db:
            if db.get(SystemSetting,'coverage_invalidated'): return False
            row=db.get(SystemSetting,'coverage_acceptance')
            if row is None: return fallback
            value=json.loads(row.value)
            return bool(value.get('reference') and value.get('all_members_verified') is True and value.get('departmentless_verified') is True)

    def accept(self,reference,actor,all_members_verified,departmentless_verified):
        if not reference or not reference.strip() or len(reference)>2000 or not actor or not actor.strip() or len(actor)>255 or all_members_verified is not True or departmentless_verified is not True:
            raise ValueError('COVERAGE_ACCEPTANCE_INVALID')
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions.begin() as db:
            lock=db.scalar(select(SystemSetting).where(SystemSetting.key=='task_queue_lock').with_for_update())
            if lock is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            state=db.scalar(select(DatasetState).where(DatasetState.id==1).with_for_update())
            if state is None: raise RuntimeError('DATABASE_SCHEMA_INCOMPLETE')
            row=db.get(SystemSetting,'coverage_acceptance')
            before=json.loads(row.value) if row else None
            after={'reference':reference.strip(),'all_members_verified':True,'departmentless_verified':True,'accepted_by':actor.strip(),'updated_at':now.isoformat()+'+00:00'}
            db.merge(SystemSetting(key='coverage_acceptance',value=json.dumps(after,ensure_ascii=False)))
            db.execute(delete(SystemSetting).where(SystemSetting.key=='coverage_invalidated'))
            state.coverage_status='unknown'
            # 不复用正在执行的旧采集；始终保存一个验收后的全量核对。
            job=SyncJob(id=secrets.token_urlsafe(12),type='reconcile',requested_by=actor.strip(),status='queued',created_at=now,updated_at=now)
            db.add(job)
            db.add(ChangeLog(object_type='settings',object_id='coverage_acceptance',source='cli',actor=actor.strip(),job_id=job.id,before_data=before,after_data=after,committed_at=now))
            return {'job_id':job.id,**after}


def main(argv=None):
    parser=argparse.ArgumentParser(description='记录企业覆盖重新验收依据，并安排全量核对')
    parser.add_argument('--reference',required=True,help='验收记录编号或摘要，禁止填写秘密')
    parser.add_argument('--actor',required=True,help='运维操作人标识')
    parser.add_argument('--all-members-verified',action='store_true',required=True)
    parser.add_argument('--departmentless-verified',action='store_true',required=True)
    args=parser.parse_args(argv)
    from app.dependencies import get_runtime
    from app.config import get_settings
    from app.feishu.binding import bind_connection
    runtime,settings=get_runtime(),get_settings()
    if not runtime: parser.error('数据库与会话密钥尚未配置')
    try:
        bind_connection(runtime.sessions,settings.feishu_app_id,settings.feishu_tenant_key)
        result=CoverageService(runtime.sessions).accept(args.reference,args.actor,args.all_members_verified,args.departmentless_verified)
    except Exception:
        # CLI 不输出 SQL、异常原文或配置。
        raise SystemExit('覆盖验收操作失败；未确认提交，请检查配置及数据库状态') from None
    print(json.dumps({'job_id':result['job_id'],'status':'queued'},ensure_ascii=False))


if __name__=='__main__': main()

```

## backend/app/sync/publisher.py
```
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
                    changes += self._upsert(db, Department, remaining.pop(key), 'department', job_id, now)
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
                fields = {k: v for k, v in value.items() if k != 'department_ids'}
                changes += self._upsert(db, Employee, fields, 'employee', job_id, now)
                db.flush()
                if value['status']=='inactive': self._revoke_employee_sessions(db,value['feishu_user_id'],job_id,now)
                before = {(r.department_id, r.is_primary, r.active) for r in db.scalars(select(EmployeeDepartment).where(EmployeeDepartment.employee_id == key))}
                after = {(d, d == value['primary_department_id'], value['status'] == 'active') for d in value['department_ids']}
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
            blocked={key for key,value in departments.items() if value['parent_id'] and value['parent_id'] not in available}
            if not blocked: break
            for key in blocked:
                value=departments.pop(key)
                deferred[('department',key)]=value
                pending.add(('department',key))
                pending.add(('department',value['parent_id']))
        available=known|set(departments)
        for key,value in list(employees.items()):
            references=set(value['department_ids'])
            if value['primary_department_id']: references.add(value['primary_department_id'])
            if references-available:
                deferred[('employee',key)]=employees.pop(key)
                pending.add(('employee',key))
                pending.update(('department',identifier) for identifier in references-available)
        for kind,identifier in pending:
            previous=db.get(PendingFact,(kind,identifier))
            value=deferred.get((kind,identifier),previous.normalized_data if previous else {})
            db.merge(PendingFact(object_type=kind,source_id=identifier,normalized_data=value,error_code='PENDING_VERIFICATION',updated_at=now))
        for kind,records in [('department',departments),('employee',employees)]:
            for identifier in records:
                db.execute(delete(PendingFact).where(PendingFact.object_type==kind,PendingFact.source_id==identifier))
        return replace(candidate,departments=departments,employees=employees,pending=sorted(pending))

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

```

## backend/app/sync/services.py
```
import secrets
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True)
class SyncJob:
    job_id: str
    type: str
    root_department_id: str | None
    requested_by: str
    status: str
    attempt: int
    created_at: datetime
    reused: bool = False
    error_code: str | None = None


class JobService:
    """任务领域服务；持久仓储可在 Task 2 worker 接入时替换。"""

    def __init__(self):
        self._jobs: dict[str, SyncJob] = {}

    def submit(self, type: str, root_department_id: str | None, requested_by: str, now: datetime) -> SyncJob:
        for job in self._jobs.values():
            if job.type == type and job.root_department_id == root_department_id and job.status in {"queued", "running"}:
                return replace(job, reused=True)
        job = SyncJob(secrets.token_urlsafe(12), type, root_department_id, requested_by, "queued", 1, now)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> SyncJob | None:
        return self._jobs.get(job_id)

    def claim(self, job_id: str) -> SyncJob:
        return self._transition(job_id, "running")

    def complete(self, job_id: str) -> SyncJob:
        return self._transition(job_id, "succeeded")

    def fail(self, job_id: str, error_code: str, now: datetime) -> SyncJob:
        job = replace(self._jobs[job_id], status="failed", error_code=error_code)
        self._jobs[job_id] = job
        return job

    def retry(self, job_id: str, requested_by: str, now: datetime) -> SyncJob:
        previous = self._jobs[job_id]
        if previous.status != "failed":
            raise ValueError("only failed jobs can be retried")
        job = replace(previous, status="queued", requested_by=requested_by, attempt=previous.attempt + 1, error_code=None, reused=False)
        self._jobs[job_id] = job
        return job

    def _transition(self, job_id: str, status: str) -> SyncJob:
        job = replace(self._jobs[job_id], status=status)
        self._jobs[job_id] = job
        return job

```

## backend/app/sync/settings.py
```
import json
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.persistence.models import SystemSetting, ChangeLog

DEFAULT = {'enabled': True, 'local_time': '03:00', 'timezone': 'Asia/Shanghai', 'updated_at': None}


class ScheduleService:
    def __init__(self, sessions): self.sessions = sessions

    def get(self):
        with self.sessions() as db:
            row = db.get(SystemSetting, 'reconcile_schedule')
            return json.loads(row.value) if row else dict(DEFAULT)

    def put(self, value, actor):
        if type(value.get('enabled')) is not bool or value.get('timezone') != 'Asia/Shanghai' or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value.get('local_time', '')):
            raise ValueError('VALIDATION_ERROR')
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as db:
            db.scalar(select(SystemSetting).where(SystemSetting.key == 'task_queue_lock').with_for_update())
            row = db.get(SystemSetting, 'reconcile_schedule')
            before = json.loads(row.value) if row else dict(DEFAULT)
            after = {**value, 'updated_at': now.isoformat()}
            db.merge(SystemSetting(key='reconcile_schedule', value=json.dumps(after)))
            db.add(ChangeLog(object_type='settings', object_id='reconcile_schedule', source='admin', actor=actor, before_data=before, after_data=after, committed_at=now.replace(tzinfo=None)))
        return after

    def due(self, now):
        with self.sessions.begin() as db:
            db.scalar(select(SystemSetting).where(SystemSetting.key == 'task_queue_lock').with_for_update())
            setting = db.get(SystemSetting, 'reconcile_schedule')
            schedule = json.loads(setting.value) if setting else DEFAULT
            local = now.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8)))
            day = local.strftime('%Y-%m-%d')
            previous = db.get(SystemSetting, 'reconcile_last_day')
            if not schedule['enabled'] or local.strftime('%H:%M') < schedule['local_time'] or previous and previous.value == day:
                return False
            # 调度标记与排队必须由同一事务完成，避免崩溃丢失日任务。
            from app.persistence.models import SyncJob
            import secrets
            active = db.scalar(select(SyncJob).where(SyncJob.type == 'reconcile', SyncJob.root_department_id.is_(None), SyncJob.status.in_(['queued', 'running'])))
            if active is None:
                db.add(SyncJob(id=secrets.token_urlsafe(12), type='reconcile', requested_by='schedule', status='queued', created_at=now, updated_at=now))
            db.merge(SystemSetting(key='reconcile_last_day', value=day))
            return True

```

## backend/app/sync/worker.py
```
"""独立同步进程，租约隔离与短事务发布。"""
import secrets
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.persistence.models import WorkerLease, SyncJob, EventInbox, SystemSetting, Department, Employee, EmployeeDepartment, PendingFact
from app.persistence.repositories import SqlSyncJobRepository
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
            self.current_job = (job.id, job.lease_generation)
            try:
                self._refresh_coverage()
                if hasattr(self.collector,'progress'): self.collector.progress=self._progress
                root=job.root_department_id if job.type == 'subtree' else None
                previous_departments,previous_users=self._previous_scope(root)
                candidate = self.collector.collect(root,previous_departments=previous_departments,previous_users=previous_users)
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
            row = db.scalar(select(SyncJob).where(SyncJob.id == claimed.id).with_for_update())
            if row.status != 'running' or row.lease_generation != claimed.lease_generation: return
            row.error_code = str(exc) if str(exc) in SAFE_SYNC_ERRORS else 'SYNC_FAILED'
            row.error_detail = None
            row.phase, row.updated_at = 'collection_failed', now
            row.status = 'queued' if row.attempt < 5 else 'failed'
            row.lease_expires_at = now+timedelta(seconds=min(900, 15 * 2 ** row.attempt)) if row.status == 'queued' else None
            row.attempt += 1 if row.status == 'queued' else 0


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
    worker = Worker(runtime.sessions, Collector(FeishuClient(settings.feishu_app_id, settings.feishu_app_secret.get_secret_value()), verified))
    stop = threading.Event()
    while not worker.acquire(utcnow()): time.sleep(5)
    worker.recover(utcnow())
    runtime.jobs.submit('reconcile', None, 'worker:startup', utcnow())
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

```

## backend/app/web.py
```
from datetime import datetime, timezone


def utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

```

## backend/migrations/env.py
```
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.persistence.models import Base


config = context.config
database_url = os.getenv("ORG_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()


```

## backend/migrations/versions/0001_initial.py
```
"""创建组织目录首版冻结表结构。"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


T = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
SID = sa.String(191, collation="utf8mb4_bin")


def upgrade():
    op.create_table("dataset_state", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("dataset_epoch", SID, nullable=False), sa.Column("data_version", sa.BigInteger(), nullable=False), sa.Column("initialization_status", sa.String(32), nullable=False), sa.Column("coverage_status", sa.String(32), nullable=False), sa.Column("last_full_sync_at", sa.DateTime()), **T)
    op.create_table("system_setting", sa.Column("key", sa.String(128, collation="utf8mb4_bin"), primary_key=True), sa.Column("value", sa.Text(), nullable=False), **T)
    op.create_table("department", sa.Column("id", SID, primary_key=True), sa.Column("feishu_department_id", SID, nullable=False, unique=True), sa.Column("parent_id", SID, sa.ForeignKey("department.id")), sa.Column("name", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("sync_quality", sa.String(32), nullable=False), sa.Column("is_virtual_root", sa.Boolean(), nullable=False), sa.Column("last_seen_at", sa.DateTime()), **T)
    op.create_table("feishu_connection", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_key", SID, unique=True), sa.Column("app_id", SID, nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("coverage_status", sa.String(32), nullable=False), **T)
    op.create_table("admin_allowlist", sa.Column("open_id", SID, primary_key=True), sa.Column("created_at", sa.DateTime(), nullable=False), **T)
    op.create_table("admin_session", sa.Column("id", SID, primary_key=True), sa.Column("open_id", SID, nullable=False), sa.Column("csrf_hash", sa.String(64), nullable=False), sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime()), **T)
    op.create_index("ix_admin_session_open_id", "admin_session", ["open_id"])
    op.create_table("api_client", sa.Column("id", SID, primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("secret_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime()), **T)
    op.create_table("sync_job", sa.Column("id", SID, primary_key=True), sa.Column("type", sa.String(32), nullable=False), sa.Column("root_department_id", SID), sa.Column("requested_by", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("phase", sa.String(64)), sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("lease_generation", sa.Integer(), nullable=False), sa.Column("lease_expires_at", sa.DateTime()), sa.Column("error_code", sa.String(64)), sa.Column("error_detail", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False), **T)
    op.create_index("ix_sync_job_status", "sync_job", ["status"])
    op.create_index("ix_sync_job_scope", "sync_job", ["type", "root_department_id", "status"])
    op.create_table("event_inbox", sa.Column("event_id", SID, primary_key=True), sa.Column("event_type", sa.String(128), nullable=False), sa.Column("object_id", SID), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("received_at", sa.DateTime(), nullable=False), **T)
    op.create_index("ix_event_inbox_status", "event_inbox", ["status"])
    op.create_table("change_log", sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("object_type", sa.String(32), nullable=False), sa.Column("object_id", SID, nullable=False), sa.Column("source", sa.String(32), nullable=False), sa.Column("actor", sa.String(255)), sa.Column("job_id", SID), sa.Column("before_data", sa.JSON()), sa.Column("after_data", sa.JSON()), sa.Column("committed_at", sa.DateTime(), nullable=False), **T)
    op.create_index("ix_change_log_committed_at", "change_log", ["committed_at"])
    op.create_table("employee", sa.Column("id", SID, primary_key=True), sa.Column("feishu_user_id", SID, nullable=False, unique=True), sa.Column("open_id", SID, unique=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("employee_no", sa.String(128)), sa.Column("status", sa.String(32), nullable=False), sa.Column("sync_quality", sa.String(32), nullable=False), sa.Column("primary_department_id", SID, sa.ForeignKey("department.id")), sa.Column("primary_store_status", sa.String(32), nullable=False), sa.Column("last_seen_at", sa.DateTime()), **T)
    op.create_table("store_profile", sa.Column("department_id", SID, sa.ForeignKey("department.id"), primary_key=True), sa.Column("is_store", sa.Boolean(), nullable=False), sa.Column("store_code", sa.String(128, collation="utf8mb4_bin"), unique=True), sa.Column("notes", sa.Text()), **T)
    op.create_table("store_code_reservation", sa.Column("store_code", sa.String(128, collation="utf8mb4_bin"), primary_key=True), sa.Column("department_id", SID, sa.ForeignKey("department.id"), nullable=False), sa.Column("reserved_at", sa.DateTime(), nullable=False), **T)
    op.create_table("sync_staging", sa.Column("job_id", SID, sa.ForeignKey("sync_job.id"), primary_key=True), sa.Column("object_type", sa.String(32), primary_key=True), sa.Column("source_id", SID, primary_key=True), sa.Column("normalized_data", sa.JSON(), nullable=False), **T)
    op.create_table("employee_department", sa.Column("employee_id", SID, sa.ForeignKey("employee.id"), primary_key=True), sa.Column("department_id", SID, sa.ForeignKey("department.id"), primary_key=True), sa.Column("is_primary", sa.Boolean(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), **T)
    op.create_table("employee_store", sa.Column("employee_id", SID, sa.ForeignKey("employee.id"), primary_key=True), sa.Column("store_id", SID, sa.ForeignKey("department.id"), primary_key=True), sa.Column("is_primary", sa.Boolean(), nullable=False), sa.Column("path", sa.JSON(), nullable=False), **T)
    op.bulk_insert(sa.table("dataset_state", sa.column("id", sa.Integer()), sa.column("dataset_epoch", SID), sa.column("data_version", sa.BigInteger()), sa.column("initialization_status", sa.String()), sa.column("coverage_status", sa.String())), [{"id": 1, "dataset_epoch": "pending", "data_version": 0, "initialization_status": "pending", "coverage_status": "unknown"}])
    op.bulk_insert(sa.table("system_setting", sa.column("key", sa.String()), sa.column("value", sa.Text())), [{"key": "task_queue_lock", "value": "1"}])


def downgrade():
    for table in ("employee_store", "employee_department", "sync_staging", "store_code_reservation", "store_profile", "employee", "change_log", "event_inbox", "sync_job", "api_client", "admin_session", "admin_allowlist", "feishu_connection", "department", "system_setting", "dataset_state"):
        op.drop_table(table)

```

## backend/migrations/versions/0002_feishu_runtime.py
```
"""飞书登录状态、身份映射与单 worker 租约。"""
from alembic import op
import sqlalchemy as sa

revision = '0002_feishu_runtime'
down_revision = '0001_initial'
branch_labels = None
depends_on = None
T = {'mysql_engine':'InnoDB','mysql_charset':'utf8mb4'}
SID = sa.String(191,collation='utf8mb4_bin')


def upgrade():
    op.create_table('oauth_state', sa.Column('digest',sa.String(64),primary_key=True),sa.Column('expires_at',sa.DateTime(),nullable=False),**T)
    op.create_table('login_identity',sa.Column('open_id',SID,primary_key=True),sa.Column('user_id',SID,nullable=False),sa.Column('tenant_key',SID,nullable=False),**T)
    op.create_table('worker_lease',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('owner',SID),sa.Column('generation',sa.Integer(),nullable=False),sa.Column('expires_at',sa.DateTime()),**T)
    op.bulk_insert(sa.table('worker_lease',sa.column('id',sa.Integer()),sa.column('generation',sa.Integer())),[{'id':1,'generation':0}])


def downgrade():
    for table in ('worker_lease','login_identity','oauth_state'): op.drop_table(table)

```

## backend/migrations/versions/0003_pending_fact.py
```
"""保留未解析事实，不创建活动部门占位。"""
from alembic import op
import sqlalchemy as sa

revision='0003_pending_fact'
down_revision='0002_feishu_runtime'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('pending_fact',sa.Column('object_type',sa.String(32),primary_key=True),sa.Column('source_id',sa.String(191,collation='utf8mb4_bin'),primary_key=True),sa.Column('normalized_data',sa.JSON(),nullable=False),sa.Column('error_code',sa.String(64),nullable=False),sa.Column('updated_at',sa.DateTime(),nullable=False),mysql_engine='InnoDB',mysql_charset='utf8mb4')


def downgrade():
    op.drop_table('pending_fact')

```

## backend/pyproject.toml
```
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "organization-directory-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "httpx==0.28.1",
  "lark-oapi==1.7.3",
  "alembic==1.16.5",
  "fastapi==0.116.1",
  "pydantic-settings==2.10.1",
  "PyMySQL[rsa]==1.1.2",
  "SQLAlchemy==2.0.43",
  "uvicorn==0.35.0",
]

[project.optional-dependencies]
test = [
  "httpx==0.28.1",
  "pytest==8.4.2",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.setuptools.packages.find]
include = ["app*"]

```

## backend/requirements.lock
```
alembic==1.16.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.7.22
cffi==2.1.1
click==8.5.0
colorama==0.4.6
cryptography==50.0.1
fastapi==0.116.1
greenlet==3.5.6
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.19
iniconfig==2.3.0
Mako==1.4.1
MarkupSafe==3.0.3
packaging==26.3
pluggy==1.6.0
pycparser==3.0
pydantic==2.13.5
pydantic-settings==2.10.1
pydantic_core==2.46.5
Pygments==2.21.0
PyMySQL==1.1.2
pytest==8.4.2
python-dotenv==1.2.3
SQLAlchemy==2.0.43
starlette==0.47.3
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.35.0

```

## backend/tests/integration/conftest.py
```
"""真实 MySQL 测试夹具：数据库由部署者提供，各用例以外层事务回滚。"""
import os
import uuid

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.database import create_mysql_engine
from app.persistence.models import DatasetState


@pytest.fixture
def mysql_sessions():
    url = os.environ.get('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('未提供 ORG_TEST_DATABASE_URL；真实 MySQL 验收尚未执行')
    parsed = make_url(url)
    if parsed.drivername != 'mysql+pymysql' or not (parsed.database or '').endswith('_test'):
        pytest.fail('集成测试仅允许 mysql+pymysql 且数据库名以 _test 结尾的独立测试库')
    engine = create_mysql_engine(url)

    class IntegrationSession(Session):
        pass

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            sessions = sessionmaker(bind=connection, class_=IntegrationSession, expire_on_commit=False, join_transaction_mode='create_savepoint')
            try:
                with sessions.begin() as db:
                    state = db.get(DatasetState, 1)
                    if state is None:
                        pytest.fail('请先对独立测试库执行 alembic upgrade head')
                    state.dataset_epoch = 'test-' + uuid.uuid4().hex
                    state.data_version = 1
                    state.initialization_status = 'complete'
                yield sessions
            finally:
                if transaction.is_active:
                    transaction.rollback()
    finally:
        engine.dispose()

```

## backend/tests/integration/test_mysql_recovery.py
```
"""恢复操作必须在真实 MySQL 上验证；缺少测试库时明确跳过。"""
from datetime import datetime, timedelta
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, DatasetState, EventInbox, OAuthState, SyncJob, WorkerLease

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from deploy.recovery import reset_restored_state


def seed_credentials(sessions):
    token = uuid4().hex
    now = datetime(2026, 9, 15)
    with sessions.begin() as db:
        old_epoch = db.get(DatasetState, 1).dataset_epoch
        db.add(AdminSession(id=token, open_id='ou_restore', csrf_hash='x' * 64,
                            expires_at=now + timedelta(days=1)))
        db.add(ApiClient(id=token, name='恢复测试', secret_hash='x' * 64, created_at=now))
    return token, old_epoch


def test_restore_requires_new_epoch_initialization_and_new_credentials(mysql_sessions):
    token, old_epoch = seed_credentials(mysql_sessions)
    now = datetime(2026, 9, 15)
    with mysql_sessions.begin() as db:
        db.add(OAuthState(digest=token, expires_at=now + timedelta(hours=1)))
        lease = db.get(WorkerLease, 1)
        assert lease is not None, '请执行完整迁移链以建立 worker 租约'
        lease.owner, lease.generation, lease.expires_at = 'old-worker', 10, now + timedelta(hours=1)
        db.add(SyncJob(id=token, type='full', requested_by='recovery-test', status='running',
                       lease_generation=4, lease_expires_at=now + timedelta(hours=1), created_at=now, updated_at=now))
        db.add(EventInbox(event_id=token, event_type='contact.user.updated_v3', payload={}, status='queued', received_at=now))
    recovery_admin = 'ou_recovery_' + uuid4().hex
    new_epoch = reset_restored_state(mysql_sessions, actor='integration-restore', admin_open_id=recovery_admin)
    with mysql_sessions() as db:
        state = db.get(DatasetState, 1)
        assert state.dataset_epoch == new_epoch != old_epoch
        assert state.initialization_status == 'pending'
        assert state.data_version == 0
        assert state.coverage_status == 'unknown'
        assert state.last_full_sync_at is None
        assert db.get(AdminSession, token).revoked_at is not None
        assert db.get(ApiClient, token).revoked_at is not None
        assert db.get(AdminAllowlist, recovery_admin) is not None
        assert db.get(OAuthState, token) is None
        assert db.get(WorkerLease, 1).generation == 11
        assert db.get(WorkerLease, 1).owner is None
        assert db.get(SyncJob, token).status == 'failed'
        assert db.get(SyncJob, token).lease_generation == 5
        assert db.get(EventInbox, token).status == 'ignored_restored'
        log = db.scalar(select(ChangeLog).where(ChangeLog.source == 'recovery', ChangeLog.object_type == 'dataset').order_by(ChangeLog.id.desc()))
        assert log.after_data['dataset_epoch'] == new_epoch


def test_recovery_audit_failure_rolls_back_epoch_and_revocations(mysql_sessions):
    token, old_epoch = seed_credentials(mysql_sessions)

    def fail_audit(db, _context, _instances):
        if any(isinstance(row, ChangeLog) and row.source == 'recovery' for row in db.new):
            raise RuntimeError('injected recovery audit failure')

    event.listen(mysql_sessions.class_, 'before_flush', fail_audit)
    try:
        with pytest.raises(RuntimeError, match='injected recovery audit failure'):
            reset_restored_state(mysql_sessions, actor='integration-restore')
    finally:
        event.remove(mysql_sessions.class_, 'before_flush', fail_audit)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).dataset_epoch == old_epoch
        assert db.get(AdminSession, token).revoked_at is None
        assert db.get(ApiClient, token).revoked_at is None

```

## backend/tests/integration/test_mysql_transactions.py
```
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from app.persistence.models import AdminSession, ApiClient, ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreProfile
from app.persistence.read_service import SqlReadService
from app.persistence.repositories import SqlIdentityRepository
from app.stores.domain import StorePatch
from app.stores.service import StoreAdminService


def test_admin_removal_preserves_revoked_session_and_denies_authentication(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    identity = SqlIdentityRepository(mysql_sessions, 't' * 32)
    open_id = 'ou_test_' + uuid4().hex
    identity.add_admin(open_id, 'integration', now)
    issued = identity.create_session(open_id, 'csrf', now + timedelta(hours=1), now)
    assert identity.authenticate_session(issued.id, now).open_id == open_id
    identity.remove_admin(open_id, 'integration', now)
    assert identity.authenticate_session(issued.id, now) is None
    with mysql_sessions() as db:
        assert db.get(AdminSession, issued.id).revoked_at == now


def test_failed_rotation_rolls_back_revocation_and_audit(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    identity = SqlIdentityRepository(mysql_sessions, 't' * 32)
    old, secret = identity.create_api_key('test-' + uuid4().hex, 'integration', now)

    def fail_replacement(db, _context, _instances):
        if any(isinstance(row, ApiClient) and row.id != old.id for row in db.new):
            raise RuntimeError('injected write failure')

    event.listen(mysql_sessions.class_, 'before_flush', fail_replacement)
    try:
        with pytest.raises(RuntimeError, match='injected write failure'):
            identity.rotate_api_key(old.id, 'integration', now)
    finally:
        event.remove(mysql_sessions.class_, 'before_flush', fail_replacement)
    assert identity.authenticate_api_key(old.id, secret) is not None
    with mysql_sessions() as db:
        logs = list(db.scalars(select(ChangeLog).where(ChangeLog.object_id == old.id)))
        assert len(logs) == 1
        assert secret not in str(logs[0].after_data)


def test_store_marking_and_cancellation_publish_projection_with_version(mysql_sessions):
    now = datetime(2026, 9, 15, 3, 0)
    prefix = 'test_' + uuid4().hex
    shop, kitchen, user = prefix + '_shop', prefix + '_kitchen', prefix + '_user'
    with mysql_sessions.begin() as db:
        db.add(Department(id=shop, feishu_department_id=shop, name='测试店', status='active', sync_quality='verified', is_virtual_root=False))
        db.flush()
        db.add(Department(id=kitchen, feishu_department_id=kitchen, parent_id=shop, name='后厨', status='active', sync_quality='verified', is_virtual_root=False))
        db.flush()
        db.add(Employee(id=user, feishu_user_id=user, name='测试员工', status='active', sync_quality='verified', primary_department_id=kitchen))
        db.flush()
        db.add(EmployeeDepartment(employee_id=user, department_id=kitchen, active=True, is_primary=True))
    stores = StoreAdminService(mysql_sessions)
    stores.apply([StorePatch(shop, True, prefix, '保留备注')], 1, 'integration', now)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
        assert db.get(EmployeeStore, (user, shop)).is_primary is True
    stores.apply([StorePatch(shop, False)], 2, 'integration', now)
    with mysql_sessions() as db:
        assert db.get(DatasetState, 1).data_version == 3
        assert db.get(StoreProfile, shop).store_code == prefix
        assert db.get(StoreProfile, shop).notes == '保留备注'
        assert db.get(EmployeeStore, (user, shop)) is None


def test_cross_page_version_change_is_rejected(mysql_sessions):
    reads = SqlReadService(mysql_sessions, 'c' * 32)
    prefix = 'test_' + uuid4().hex
    with mysql_sessions.begin() as db:
        db.add_all([Department(id=prefix + str(n), feishu_department_id=prefix + str(n), name='测试部门', status='active', sync_quality='verified', is_virtual_root=False) for n in range(2)])
    _, meta = reads.list_departments(limit=1)
    assert meta['next_cursor']
    with mysql_sessions.begin() as db:
        db.get(DatasetState, 1).data_version += 1
    with pytest.raises(RuntimeError, match='DATASET_CHANGED'):
        reads.list_departments(limit=1, cursor=meta['next_cursor'])

```

## backend/tests/test_cursor_and_jobs.py
```
from datetime import datetime, timezone

import pytest

from app.public_api.cursor import CursorCodec, DatasetChanged, InvalidCursor
from app.sync.services import JobService


def test_cursor_binds_filters_epoch_version_and_last_id():
    codec = CursorCodec("c" * 32)
    cursor = codec.encode(epoch="EpochA", version=8, filters={"status": "active"}, last_id="DepZ")

    page = codec.decode(cursor, epoch="EpochA", version=8, filters={"status": "active"})

    assert page.last_id == "DepZ"
    with pytest.raises(DatasetChanged):
        codec.decode(cursor, epoch="EpochA", version=9, filters={"status": "active"})
    with pytest.raises(InvalidCursor):
        codec.decode(cursor, epoch="EpochA", version=8, filters={"status": "inactive"})


def test_running_job_with_same_scope_is_reused_and_failed_job_can_retry():
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    service = JobService()
    first = service.submit("subtree", "DepA", "admin:ou1", now)
    duplicate = service.submit("subtree", "DepA", "admin:ou1", now)

    assert duplicate.job_id == first.job_id
    assert duplicate.reused is True
    service.fail(first.job_id, "REMOTE_TIMEOUT", now)
    retried = service.retry(first.job_id, "admin:ou1", now)
    assert retried.attempt == 2
    assert retried.status == "queued"


```

## backend/tests/test_feishu_adapter.py
```
import httpx
import pytest


def test_oidc_uses_app_token_then_nested_user_token():
    from app.feishu.client import FeishuClient
    def respond(request):
        if request.url.path.endswith('/app_access_token/internal'):
            return httpx.Response(200, json={"code": 0, "app_access_token": "app-token", "expire": 7200})
        if request.url.path.endswith('/oidc/access_token'):
            assert request.headers['authorization'] == 'Bearer app-token'
            return httpx.Response(200, json={"code": 0, "data": {"access_token": "user-token", "expires_in": 7200}})
        assert request.url.path.endswith('/user_info')
        assert request.headers['authorization'] == 'Bearer user-token'
        return httpx.Response(200, json={"code": 0, "data": {"open_id": "ou_a", "user_id": "u", "tenant_key": "tenant"}})
    api = FeishuClient('app', 'secret', httpx.Client(transport=httpx.MockTransport(respond)))
    assert api.login('code')['tenant_key'] == 'tenant'


def test_pagination_rejects_repeated_token_and_masks_upstream_errors():
    from app.feishu.client import FeishuClient
    def respond(request):
        if request.url.path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "sensitive", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"has_more": True, "page_token": "same", "department_ids": []}})
    api = FeishuClient('a', 's', httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(RuntimeError, match='INVALID_PAGINATION'):
        list(api.pages('scopes'))


def test_event_identity_and_missing_object_are_not_silently_accepted():
    from app.feishu.events import normalize_event
    payload = {"header": {"event_id": "e", "event_type": "contact.user.deleted_v3", "app_id": "a", "tenant_key": "t"}, "event": {"object": {}}}
    result = normalize_event(payload, 'a', 't')
    assert result['status'] == 'failed'
    assert result['payload']['error_code'] == 'EVENT_OBJECT_ID_MISSING'
    with pytest.raises(ValueError, match='EVENT_IDENTITY_MISMATCH'):
        normalize_event(payload, 'other', 't')


def test_scope_change_is_processable_without_object_id():
    from app.feishu.events import normalize_event
    result=normalize_event({'header':{'event_id':'scope','event_type':'contact.scope.updated_v3','app_id':'a','tenant_key':'t'},'event':{}},'a','t')
    assert result['status']=='queued'

```

## backend/tests/test_feishu_http.py
```
import hashlib
import hmac
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.config import get_settings, Settings
from app.dependencies import get_admin_identity, get_runtime


def test_session_bootstrap_requires_matching_cookie_and_does_not_put_csrf_in_url():
    secret='s'*32
    app.dependency_overrides[get_settings]=lambda: Settings(session_secret=secret)
    app.dependency_overrides[get_admin_identity]=lambda: SimpleNamespace(open_id='ou',csrf_hash=hmac.new(secret.encode(),b'csrf',hashlib.sha256).hexdigest())
    try:
        client=TestClient(app)
        assert client.get('/admin/auth/session').status_code == 403
        client.cookies.set('org_csrf','csrf')
        response=client.get('/admin/auth/session')
        assert response.json() == {'data':{'open_id':'ou','csrf_token':'csrf'},'meta':{}}
        assert response.headers['cache-control'] == 'no-store'
    finally: app.dependency_overrides.clear()


def test_schedule_routes_and_login_unconfigured_are_safe():
    client=TestClient(app)
    assert client.get('/admin/auth/login').status_code == 503
    assert client.get('/admin/api/settings/reconcile-schedule').status_code == 401
    assert client.put('/admin/api/settings/reconcile-schedule',json={}).status_code == 401


def test_connection_unknown_is_degraded_and_secret_is_never_echoed():
    from app.feishu.health import connection_summary
    settings=Settings(feishu_app_id='cli_sensitive',feishu_app_secret='NEVER-ECHO',feishu_tenant_key='tenant_sensitive')
    result=connection_summary(settings,None)
    assert result['status']=='degraded'
    assert 'NEVER-ECHO' not in str(result)
    assert result['app_id_masked'] != 'cli_sensitive'

```

## backend/tests/test_feishu_listener.py
```
from types import SimpleNamespace
from test_sync_persistence import sessions
from app.config import Settings
from app.persistence.models import SyncJob, SystemSetting, EventInbox
from sqlalchemy import select


def test_listener_startup_and_reconnected_enqueue_one_reconcile_without_claiming_connected(sessions):
    from app.feishu.listener import Listener
    listener=Listener(sessions,Settings(feishu_app_id='a',feishu_app_secret='s',feishu_tenant_key='t'))
    listener.starting()
    listener.starting()
    with sessions() as db:
        assert len(list(db.scalars(select(SyncJob)))) == 1
        assert 'degraded' in db.get(SystemSetting,'feishu_connection_observation').value
    listener.reconnected()
    with sessions() as db: assert len(list(db.scalars(select(SyncJob)))) == 1


def test_listener_callback_only_inboxes_and_never_swallows_persistence_failure(sessions):
    from app.feishu.listener import Listener
    listener=Listener(sessions,Settings(feishu_app_id='a',feishu_app_secret='s',feishu_tenant_key='t'))
    payload={'header':{'event_id':'e','event_type':'contact.user.created_v3','app_id':'a','tenant_key':'t'},'event':{'object':{'user_id':'u'}}}
    listener.receive(payload)
    listener.receive(payload)
    with sessions() as db: assert db.get(EventInbox,'e').status == 'queued'

```

## backend/tests/test_http_contract.py
```
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_liveness_works_without_production_configuration_and_readiness_is_explicit():
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "DATABASE_NOT_CONFIGURED"


def test_anonymous_public_request_is_401_with_error_envelope():
    response = client.get("/api/v1/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_machine_credential_cannot_use_admin_write_endpoint():
    response = client.post(
        "/admin/api/sync/jobs",
        headers={"Authorization": "Bearer client.secret"},
        json={"type": "full"},
    )
    assert response.status_code == 401


def test_initialized_status_uses_data_meta_envelope_with_dependency_replacement():
    from app.dependencies import get_public_identity, get_read_service

    class FakeReadService:
        def status(self):
            return ({"initialization_status": "complete"}, {"dataset_epoch": "EpochA", "data_version": 7})

    app.dependency_overrides[get_public_identity] = lambda: {"client_id": "ClientA"}
    app.dependency_overrides[get_read_service] = FakeReadService
    try:
        response = client.get("/api/v1/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "data": {"initialization_status": "complete"},
        "meta": {"dataset_epoch": "EpochA", "data_version": 7},
    }


def test_management_contract_registers_store_audit_allowlist_and_client_routes():
    paths = app.openapi()["paths"]
    expected = {
        "/admin/api/stores/batch/preview",
        "/admin/api/stores/batch/apply",
        "/admin/api/stores/{store_id}",
        "/admin/api/change-logs",
        "/admin/api/admin-allowlist",
        "/admin/api/admin-allowlist/{open_id}",
        "/admin/api/api-clients",
        "/admin/api/api-clients/{client_id}/rotate",
        "/admin/api/api-clients/{client_id}/revoke",
    }
    assert expected <= set(paths)

```

## backend/tests/test_identity.py
```
from datetime import datetime, timedelta, timezone

from app.identity.services import ApiCredentialService, SessionService


NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_session_requires_allowlisted_identity_and_valid_csrf_for_writes():
    sessions = SessionService(secret="s" * 32, allowlist={"ou_Admin"})
    issued = sessions.create("ou_Admin", NOW)

    identity = sessions.authenticate(issued.session_token, NOW + timedelta(minutes=1))

    assert identity.open_id == "ou_Admin"
    assert sessions.verify_csrf(identity, issued.csrf_token) is True
    assert sessions.verify_csrf(identity, "wrong") is False


def test_removing_allowlist_entry_immediately_revokes_session():
    sessions = SessionService(secret="s" * 32, allowlist={"ou_Admin"})
    issued = sessions.create("ou_Admin", NOW)
    sessions.set_allowlist(set())

    assert sessions.authenticate(issued.session_token, NOW) is None


def test_source_id_allowlist_is_case_sensitive():
    sessions = SessionService(secret="s" * 32, allowlist={"ou_Admin"})

    assert sessions.create("ou_admin", NOW) is None


def test_api_secret_is_hashed_returned_once_and_revocation_is_immediate():
    service = ApiCredentialService(pepper="p" * 32)
    issued = service.issue("Payroll", NOW)

    assert issued.secret not in service.export_records()[0].secret_hash
    assert service.authenticate(issued.client_id, issued.secret, NOW) is not None
    service.revoke(issued.client_id, NOW)
    assert service.authenticate(issued.client_id, issued.secret, NOW) is None


```

## backend/tests/test_mysql_schema.py
```
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.persistence.models import AdminSession, ApiClient, Department, StoreProfile


def test_business_tables_compile_as_innodb_utf8mb4_and_source_ids_are_binary_collated():
    department_ddl = str(CreateTable(Department.__table__).compile(dialect=mysql.dialect()))
    store_ddl = str(CreateTable(StoreProfile.__table__).compile(dialect=mysql.dialect()))
    client_ddl = str(CreateTable(ApiClient.__table__).compile(dialect=mysql.dialect()))

    for ddl in (department_ddl, store_ddl, client_ddl):
        assert "ENGINE=InnoDB" in ddl
        assert "CHARSET=utf8mb4" in ddl
    assert "utf8mb4_bin" in department_ddl
    assert "utf8mb4_bin" in client_ddl


def test_revoked_sessions_can_be_retained_after_allowlist_entry_is_deleted():
    ddl = str(CreateTable(AdminSession.__table__).compile(dialect=mysql.dialect()))
    assert "FOREIGN KEY(open_id)" not in ddl
    assert any(index.name == "ix_admin_session_open_id" for index in AdminSession.__table__.indexes)

```

## backend/tests/test_review_fixes.py
```
from datetime import datetime, timezone

from sqlalchemy.dialects import mysql

from app.main import app
from app.persistence.repositories import SqlIdentityRepository
from app.stores.domain import UNSET, StorePatch, merge_store_patch
from app.web import utc_datetime


def test_persistent_session_query_has_explicit_allowlist_join():
    statement = SqlIdentityRepository.session_auth_statement("sid", datetime(2026, 9, 15))
    sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "JOIN admin_allowlist ON admin_allowlist.open_id = admin_session.open_id" in sql


def test_store_patch_preserves_omitted_fields_and_null_can_clear_code():
    current = {"is_store": True, "store_code": "A-01", "notes": "历史备注"}
    toggled = merge_store_patch(current, StorePatch("DepA", False))
    cleared = merge_store_patch(current, StorePatch("DepA", True, store_code=None))
    notes_only = merge_store_patch(current, StorePatch("DepA", True, notes="新备注"))
    assert toggled == {"is_store": False, "store_code": "A-01", "notes": "历史备注"}
    assert cleared == {"is_store": True, "store_code": None, "notes": "历史备注"}
    assert notes_only == {"is_store": True, "store_code": "A-01", "notes": "新备注"}


def test_naive_database_datetime_is_serialized_as_utc():
    assert utc_datetime(datetime(2026, 9, 15, 3, 4, 5)).isoformat() == "2026-09-15T03:04:05+00:00"
    aware = datetime(2026, 9, 15, 3, 4, 5, tzinfo=timezone.utc)
    assert utc_datetime(aware) is aware


def test_store_employee_endpoints_support_cross_endpoint_version_and_admin_alias():
    schema = app.openapi()["paths"]
    public_parameters = {item["name"] for item in schema["/api/v1/stores/{store_id}/employees"]["get"]["parameters"]}
    assert {"dataset_epoch", "data_version"} <= public_parameters
    assert "/admin/api/stores/{store_id}/employees" in schema


def test_task_list_has_stable_cursor_parameter():
    parameters = {item["name"] for item in app.openapi()["paths"]["/admin/api/sync/jobs"]["get"]["parameters"]}
    assert "cursor" in parameters

```

## backend/tests/test_store_commands.py
```
from app.stores.domain import StorePatch, validate_store_changes


def test_store_code_is_trimmed_and_empty_code_becomes_none():
    changes = validate_store_changes(
        [StorePatch("DepA", True, "  AbC-1  ", " note "), StorePatch("DepB", False, "   ", None)],
        departments={"DepA": {"status": "active", "is_virtual_root": False}, "DepB": {"status": "active", "is_virtual_root": False}},
    )
    assert changes[0].store_code == "AbC-1"
    assert changes[1].store_code is None


def test_virtual_root_and_inactive_department_cannot_be_new_stores():
    departments = {"Root": {"status": "active", "is_virtual_root": True}, "Old": {"status": "inactive", "is_virtual_root": False}}

    errors = validate_store_changes([StorePatch("Root", True), StorePatch("Old", True)], departments=departments, raise_errors=False)

    assert [(error.department_id, error.code) for error in errors] == [("Root", "VIRTUAL_ROOT"), ("Old", "DEPARTMENT_INACTIVE")]


def test_duplicate_codes_are_case_sensitive_but_exact_duplicates_are_rejected():
    departments = {key: {"status": "active", "is_virtual_root": False} for key in ("A", "B", "C")}

    errors = validate_store_changes(
        [StorePatch("A", True, "Shop"), StorePatch("B", True, "shop"), StorePatch("C", True, "Shop")],
        departments=departments,
        raise_errors=False,
    )

    assert [(error.department_id, error.code) for error in errors] == [("C", "DUPLICATE_STORE_CODE")]

```

## backend/tests/test_store_resolution.py
```
from app.directory.domain import Department, Employee, Membership, resolve_employee_stores


def test_nearest_store_is_selected_for_each_membership_without_duplicates():
    departments = {
        "hq": Department("hq", None, False),
        "north": Department("north", "hq", True),
        "kitchen": Department("kitchen", "north", False),
        "station": Department("station", "kitchen", True),
    }
    employee = Employee("u1", "active", "kitchen")
    memberships = [Membership("u1", "kitchen"), Membership("u1", "station")]

    result = resolve_employee_stores(employee, memberships, departments)

    assert result.store_ids == ["north", "station"]
    assert result.primary_store_id == "north"
    assert result.primary_store_status == "resolved"


def test_headquarters_primary_department_does_not_promote_part_time_store():
    departments = {
        "hq": Department("hq", None, False),
        "university": Department("university", "hq", True),
    }
    employee = Employee("u1", "active", "hq")
    memberships = [Membership("u1", "hq"), Membership("u1", "university")]

    result = resolve_employee_stores(employee, memberships, departments)

    assert result.store_ids == ["university"]
    assert result.primary_store_id is None
    assert result.primary_store_status == "not_in_store"


def test_missing_ancestor_makes_primary_store_unknown_but_keeps_other_store():
    departments = {"shop": Department("shop", None, True), "orphan": Department("orphan", "missing", False)}
    employee = Employee("u1", "active", "orphan")
    memberships = [Membership("u1", "orphan"), Membership("u1", "shop")]

    result = resolve_employee_stores(employee, memberships, departments)

    assert result.store_ids == ["shop"]
    assert result.primary_store_status == "unknown"


def test_inactive_employee_has_no_current_store_assignment():
    departments = {"shop": Department("shop", None, True)}
    employee = Employee("u1", "inactive", "shop")

    result = resolve_employee_stores(employee, [Membership("u1", "shop")], departments)

    assert result.store_ids == []
    assert result.primary_store_status == "inactive"


def test_primary_department_must_be_an_active_membership():
    departments = {"a": Department("a", None, True), "b": Department("b", None, True)}
    employee = Employee("u1", "active", "a")

    result = resolve_employee_stores(employee, [Membership("u1", "b")], departments)

    assert result.store_ids == ["b"]
    assert result.primary_store_status == "inconsistent"


```

## backend/tests/test_sync_collection.py
```
import pytest


def test_partial_page_failure_never_returns_candidate():
    from app.sync.collector import Collector
    class API:
        def pages(self, resource, **params):
            yield {"department_ids": ["a"], "user_ids": [], "group_ids": []}
            raise RuntimeError("PERMISSION_DENIED")
    with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
        Collector(API()).collect()


def test_missing_primary_and_conflicting_orders_are_not_inferred():
    from app.sync.collector import normalize_user
    raw = {"user_id": "u", "name": "员工", "department_ids": ["a", "b"], "status": {"is_resigned": False}}
    assert normalize_user(raw)["primary_department_id"] is None
    raw["orders"] = [{"department_id": "a", "is_primary_dept": True}, {"department_id": "b", "is_primary_dept": True}]
    assert normalize_user(raw)["sync_quality"] == "inconsistent"


def test_unreadable_details_are_pending_and_deleted_event_cannot_override_current_fact():
    from app.sync.collector import Collector
    class API:
        def detail(self, kind, identifier):
            if identifier == "missing":
                raise RuntimeError("PERMISSION_DENIED")
            return {"user_id": identifier, "name": "恢复员工", "department_ids": [], "status": {"is_resigned": False}}
    candidate = Collector(API()).event("contact.user.deleted_v3", "restored")
    assert candidate.employees["restored"]["status"] == "active"
    assert Collector(API()).event("contact.user.deleted_v3", "missing").pending == [("employee", "missing")]


def test_unreadable_ancestor_and_inconsistent_primary_stay_unknown():
    from app.directory.domain import Department, Employee, Membership, resolve_employee_stores
    departments = {"a": Department("a", None, False, sync_quality="pending_verification")}
    assert resolve_employee_stores(Employee("u", "active", "a"), [Membership("u", "a")], departments).primary_store_status == "unknown"
    assert resolve_employee_stores(Employee("u", "active", None, "inconsistent"), [Membership("u", "a")], departments).primary_store_status == "inconsistent"


def test_full_collection_traverses_root_and_event_closes_virtual_root():
    from app.sync.collector import Collector
    class API:
        def pages(self,resource,**params):
            if resource=='scopes': yield {'department_ids':[], 'user_ids':[], 'group_ids':[]}
            elif resource=='children': yield {'items':[{'open_department_id':'a'}] if params['department_id']=='0' else []}
            else: yield {'items':[{'user_id':'u'}] if params['department_id']=='a' else []}
        def detail(self,kind,identifier):
            if kind=='user': return {'user_id':'u','name':'员工','department_ids':['a'],'status':{'is_resigned':False}}
            assert identifier=='a'
            return {'open_department_id':'a','parent_department_id':'0','name':'部门','status':{'is_deleted':False}}
    assert set(Collector(API()).collect().employees)=={'u'}
    assert Collector(API()).event('contact.user.updated_v3','u').departments['0']['parent_id'] is None


def test_collection_reports_real_counts_with_unknown_totals():
    from app.sync.collector import Collector
    class API:
        def pages(self,resource,**params):
            yield {'department_ids':[], 'user_ids':[], 'group_ids':[]} if resource=='scopes' else {'items':[]}
    observations=[]
    collector=Collector(API(),progress=lambda **value: observations.append(value))
    collector.collect()
    assert observations[-1]['departments_processed']==1
    assert observations[-1]['employees_processed']==0
    assert observations[-1]['departments_total'] is None


def test_missing_department_field_is_unreadable_not_empty_membership():
    from app.sync.collector import Collector
    class API:
        def detail(self,kind,identifier): return {'user_id':'u','name':'员工'}
    result=Collector(API()).event('contact.user.updated_v3','u')
    assert result.employees=={}
    assert result.pending==[('employee','u')]


def test_subtree_rechecks_former_members_after_move_and_keeps_other_memberships():
    from app.sync.collector import Collector
    class API:
        def pages(self,resource,**params):
            yield {'department_ids':['old'],'user_ids':[],'group_ids':[]} if resource=='scopes' else {'items':[]}
        def detail(self,kind,identifier):
            if kind=='user': return {'user_id':'u','name':'移动员工','department_ids':['new','other'],'status':{'is_resigned':False}}
            return {'open_department_id':identifier,'parent_department_id':'new' if identifier=='moved' else '0','name':identifier,'status':{'is_deleted':False}}
    result=Collector(API()).collect('old',previous_departments={'moved'},previous_users={'u'})
    assert result.employees['u']['department_ids']==['new','other']
    assert result.departments['moved']['parent_id']=='new'


def test_missing_lifecycle_or_parent_is_not_inferred_as_active_or_root():
    from app.sync.collector import normalize_user, normalize_department
    with pytest.raises(RuntimeError): normalize_user({'user_id':'u','name':'员工','department_ids':[]})
    with pytest.raises(RuntimeError): normalize_department({'open_department_id':'a','name':'部门','status':{'is_deleted':False}})

```

## backend/tests/test_sync_persistence.py
```
"""SQLite 仅验证事务业务；不替代 MySQL 行锁并发验收。"""
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import BigInteger
from sqlalchemy.orm import sessionmaker
from app.persistence.models import Base, DatasetState, SystemSetting, Department, Employee, EmployeeDepartment, StoreProfile, EmployeeStore, SyncJob


@compiles(BigInteger, 'sqlite')
def sqlite_integer(element, compiler, **kwargs):
    return 'INTEGER'


@pytest.fixture
def sessions():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.create_collation('utf8mb4_bin', lambda a, b: (a > b) - (a < b))
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(DatasetState(id=1, dataset_epoch='e', data_version=1, initialization_status='complete'))
        db.add(SystemSetting(key='task_queue_lock', value='1'))
    yield factory
    engine.dispose()


def test_preview_counts_descendant_changes_but_excludes_nested_store(sessions):
    from app.stores.service import StoreAdminService
    from app.stores.domain import StorePatch
    with sessions.begin() as db:
        for identifier, parent in [('a', None), ('b', 'a'), ('c', 'b')]:
            db.add(Department(id=identifier, feishu_department_id=identifier, parent_id=parent, name=identifier, sync_quality='complete'))
            db.flush()
        db.add(StoreProfile(department_id='c', is_store=True))
        for identifier, department in [('u', 'b'), ('v', 'c')]:
            db.add(Employee(id=identifier, feishu_user_id=identifier, name=identifier, primary_department_id=department, sync_quality='complete'))
            db.flush()
            db.add(EmployeeDepartment(employee_id=identifier, department_id=department))
    assert StoreAdminService(sessions).preview([StorePatch('a', True)], 1)['affected_employee_count'] == 1
    StoreAdminService(sessions).apply([StorePatch('a', True)], 1, 'admin:a', datetime.now())
    with sessions() as db:
        assert db.get(EmployeeStore, ('u', 'a')).path == ['b', 'a']


def test_publication_is_atomic_preserves_missing_and_noop_version(sessions):
    from app.sync.publisher import Publisher
    from app.sync.collector import Candidate
    with sessions.begin() as db:
        db.add(SyncJob(id='job', type='full', requested_by='test', status='running', lease_generation=1, lease_expires_at=datetime.now()+timedelta(hours=1), created_at=datetime.now(), updated_at=datetime.now()))
    candidate = Candidate(departments={'a': {'id':'a', 'feishu_department_id':'a', 'parent_id':None, 'name':'门店', 'status':'active', 'sync_quality':'complete', 'is_virtual_root':False}}, full=True)
    publisher = Publisher(sessions)
    publisher.publish(candidate, 'job', 1)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
        assert db.get(SyncJob, 'job').status == 'succeeded'
    with sessions.begin() as db:
        job=db.get(SyncJob,'job'); job.status='running'; job.lease_expires_at=datetime.now()+timedelta(hours=1)
    publisher.publish(candidate, 'job', 1)
    with sessions() as db:
        assert db.get(DatasetState, 1).data_version == 2
    with pytest.raises(ValueError, match='STALE_LEASE'):
        publisher.publish(Candidate(), 'job', 0)


def test_schedule_default_validation_and_daily_deduplication(sessions):
    from app.sync.settings import ScheduleService
    schedule = ScheduleService(sessions)
    assert schedule.get()['local_time'] == '03:00'
    assert schedule.due(datetime(2026,9,14,19,0)) is True
    assert schedule.due(datetime(2026,9,14,19,1)) is False
    with pytest.raises(ValueError):
        schedule.put({'enabled': True, 'local_time':'25:00', 'timezone':'Asia/Shanghai'}, 'admin')


def test_oauth_state_single_use_bound_to_browser_and_identity(sessions):
    from app.feishu.oauth import OAuthService
    from app.config import Settings
    from app.persistence.models import AdminAllowlist
    settings=Settings(session_secret='s'*32, feishu_app_id='a', feishu_app_secret='secret', feishu_redirect_uri='https://example/admin/auth/callback', feishu_tenant_key='t')
    class API:
        def login(self, code): return {'open_id':'ou', 'user_id':'u', 'tenant_key':'t'}
    with sessions.begin() as db: db.add(AdminAllowlist(open_id='ou', created_at=datetime.now()))
    service=OAuthService(sessions, settings, API())
    state=service.begin()
    with pytest.raises(ValueError): service.complete(state, 'wrong', 'code')
    session, csrf=service.complete(state, state, 'code')
    assert session.open_id == 'ou' and csrf
    with pytest.raises(ValueError): service.complete(state, state, 'code')


def test_employee_detail_explains_store_path_and_department_notes(sessions):
    from app.persistence.read_service import SqlReadService
    with sessions.begin() as db:
        db.add(Department(id='a',feishu_department_id='a',name='门店',sync_quality='complete')); db.flush()
        db.add(StoreProfile(department_id='a',is_store=True,notes='备注'))
        db.add(Employee(id='u',feishu_user_id='u',name='员工',primary_department_id='a')); db.flush()
        db.add(EmployeeDepartment(employee_id='u',department_id='a'))
        db.add(EmployeeStore(employee_id='u',store_id='a',is_primary=True,path=['a']))
    reads=SqlReadService(sessions,'s'*32)
    assert reads.get_department('a')[0]['notes']=='备注'
    employee=reads.get_employee('u')[0]
    assert employee['stores'][0]['path']==['a']
    assert employee['stores'][0]['name']=='门店'
    assert employee['departments'][0]['path']==['门店']


def test_change_log_filters_actor_action_and_utc_bounds(sessions):
    from app.admin.router import change_logs
    from app.persistence.models import ChangeLog
    from types import SimpleNamespace
    from datetime import timezone
    with sessions.begin() as db:
        db.add(ChangeLog(object_type='store',object_id='a',source='admin',actor='admin:a',before_data=None,after_data={'is_store':True},committed_at=datetime(2026,9,15,1)))
        db.add(ChangeLog(object_type='store',object_id='b',source='admin',actor='admin:b',before_data={},after_data={},committed_at=datetime(2026,9,15,2)))
    data=change_logs(actor='admin:a',action='create',committed_after=datetime(2026,9,15,tzinfo=timezone.utc),committed_before=None,limit=100,cursor=None,identity=None,runtime=SimpleNamespace(sessions=sessions))
    assert [row['object_id'] for row in data['data']]==['a']


def test_failed_events_are_visible_and_retry_rejects_missing_identifier(sessions):
    from app.admin.router import list_events, retry_event
    from app.persistence.models import EventInbox
    from types import SimpleNamespace
    from fastapi import HTTPException
    with sessions.begin() as db:
        db.add(EventInbox(event_id='e',event_type='contact.user.deleted_v3',object_id=None,payload={'error_code':'EVENT_OBJECT_ID_MISSING'},status='failed',received_at=datetime.now()))
    runtime=SimpleNamespace(sessions=sessions)
    result=list_events(status='failed',limit=100,cursor=None,identity=None,runtime=runtime)
    assert result['data'][0]['error_code']=='EVENT_OBJECT_ID_MISSING'
    with pytest.raises(HTTPException): retry_event('e',(SimpleNamespace(open_id='admin'),None),runtime)


def test_publication_cycle_failure_rolls_back_all_facts_and_version(sessions):
    from app.sync.publisher import Publisher
    from app.sync.collector import Candidate
    def department(identifier,parent): return {'id':identifier,'feishu_department_id':identifier,'parent_id':parent,'name':identifier,'status':'active','sync_quality':'complete','is_virtual_root':False}
    candidate=Candidate(departments={'safe':department('safe',None),'a':department('a','b'),'b':department('b','a')})
    with pytest.raises(RuntimeError,match='DEPARTMENT_CYCLE'): Publisher(sessions).publish(candidate)
    with sessions() as db:
        assert list(db.scalars(select(Department)))==[]
        assert db.get(DatasetState,1).data_version==1


def test_database_connection_binding_rejects_different_application_or_tenant(sessions):
    from app.feishu.binding import bind_connection
    bind_connection(sessions,'app','tenant')
    bind_connection(sessions,'app','tenant')
    with pytest.raises(RuntimeError,match='CONFIG_BINDING_MISMATCH'): bind_connection(sessions,'other','tenant')
    with pytest.raises(RuntimeError,match='CONFIG_BINDING_MISMATCH'): bind_connection(sessions,'app','other')


def test_partial_department_update_cannot_create_cycle_with_existing_parent(sessions):
    from app.sync.publisher import Publisher
    from app.sync.collector import Candidate
    with sessions.begin() as db:
        db.add(Department(id='a',feishu_department_id='a',name='a',sync_quality='complete'));db.flush()
        db.add(Department(id='b',feishu_department_id='b',name='b',parent_id='a',sync_quality='complete'))
    candidate=Candidate(departments={'a':{'id':'a','feishu_department_id':'a','parent_id':'b','name':'a','status':'active','sync_quality':'complete','is_virtual_root':False}})
    with pytest.raises(RuntimeError,match='DEPARTMENT_CYCLE'): Publisher(sessions).publish(candidate)
    with sessions() as db: assert db.get(Department,'a').parent_id is None

```

## backend/tests/test_sync_worker.py
```
from datetime import datetime, timedelta
import pytest
from test_sync_persistence import sessions
from app.persistence.models import WorkerLease, SyncJob, EventInbox, DatasetState


def test_single_worker_lease_fences_old_owner_and_recovers_expired_job(sessions):
    from app.sync.worker import Worker
    now = datetime(2026,9,15)
    with sessions.begin() as db:
        db.add(WorkerLease(id=1, generation=0))
        db.add(SyncJob(id='j', type='full', requested_by='test', status='running', lease_generation=1, lease_expires_at=now-timedelta(seconds=1), created_at=now, updated_at=now))
    a, b = Worker(sessions, None, owner='a'), Worker(sessions, None, owner='b')
    assert a.acquire(now) is True
    assert b.acquire(now) is False
    assert b.acquire(now+timedelta(minutes=3)) is True
    assert a.renew(now+timedelta(minutes=3)) is False
    b.recover(now+timedelta(minutes=3))
    with sessions() as db:
        job=db.get(SyncJob,'j')
        assert job.status == 'queued' and job.lease_generation == 2


def test_worker_failed_collection_does_not_publish_version(sessions):
    from app.sync.worker import Worker, utcnow
    from app.persistence.repositories import SqlSyncJobRepository
    class Collector:
        def collect(self, root=None, **kwargs): raise RuntimeError('FEISHU_API_ERROR')
    with sessions.begin() as db: db.add(WorkerLease(id=1, generation=0))
    job,_=SqlSyncJobRepository(sessions).submit('full', None, 'test', utcnow())
    worker=Worker(sessions, Collector())
    assert worker.acquire(utcnow())
    worker.step()
    with sessions() as db:
        assert db.get(DatasetState,1).data_version == 1
        job=db.get(SyncJob,job.id)
        assert job.error_code == 'FEISHU_API_ERROR'
        assert job.status == 'queued' and job.lease_expires_at > utcnow()


def test_stale_worker_cannot_rewrite_processed_event(sessions):
    from app.sync.worker import Worker, utcnow
    with sessions.begin() as db:
        db.add(WorkerLease(id=1,owner='new',generation=2,expires_at=utcnow()+timedelta(minutes=1)))
        db.add(EventInbox(event_id='e',event_type='contact.user.updated_v3',object_id='u',payload={},status='succeeded',received_at=utcnow()))
    old=Worker(sessions,None,owner='old'); old.generation=1
    old._fail_event('e')
    with sessions() as db: assert db.get(EventInbox,'e').status=='succeeded'

```

## backend/tests/test_task2_review_fixes.py
```
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import select, event
from sqlalchemy.exc import OperationalError
from fastapi.testclient import TestClient
from test_sync_persistence import sessions
from app.persistence.models import Department, Employee, EmployeeDepartment, LoginIdentity, AdminAllowlist, AdminSession, ChangeLog, SystemSetting, SyncJob, DatasetState, WorkerLease
from app.sync.collector import Candidate, normalize_user
from app.sync.publisher import Publisher
from app.feishu.oauth import OAuthService
from app.config import Settings


def oauth(sessions, user_id='u'):
    class API:
        def login(self, code): return {'open_id':'ou','user_id':user_id,'tenant_key':'t'}
    return OAuthService(sessions,Settings(session_secret='s'*32,feishu_app_id='a',feishu_app_secret='s',feishu_tenant_key='t'),API())


def seed_admin(sessions,status='active'):
    with sessions.begin() as db:
        db.add(AdminAllowlist(open_id='ou',created_at=datetime.now()))
        db.add(LoginIdentity(open_id='ou',user_id='u',tenant_key='t'))
        db.add(Employee(id='u',feishu_user_id='u',name='员工',status=status,sync_quality='complete'))
        db.add(AdminSession(id='session',open_id='ou',csrf_hash='hash',expires_at=datetime.now()+timedelta(days=1)))


def test_oauth_binding_mismatch_preserves_mapping_and_commits_safe_audit(sessions):
    seed_admin(sessions)
    service=oauth(sessions,'different-user'); state=service.begin()
    with pytest.raises(ValueError,match='LOGIN_IDENTITY_MISMATCH'): service.complete(state,state,'sensitive-code')
    with sessions() as db:
        assert db.get(LoginIdentity,'ou').user_id=='u'
        rows=list(db.scalars(select(ChangeLog)))
        assert rows[-1].after_data=={'error_code':'LOGIN_IDENTITY_MISMATCH'}
        assert 'sensitive-code' not in str(rows[-1].after_data)
        assert len(list(db.scalars(select(AdminSession))))==1


def test_unknown_department_and_dependent_employee_are_deferred_without_fake_facts(sessions):
    employee=normalize_user({'user_id':'new','name':'新员工','department_ids':['missing'],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'new':employee},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Department,'missing') is None
        assert db.get(Employee,'new') is None
        from app.persistence.models import PendingFact
        assert db.get(PendingFact,('employee','new')).normalized_data['department_ids']==['missing']


def test_existing_employee_retains_relations_when_new_ancestor_unreadable(sessions):
    with sessions.begin() as db:
        db.add(Department(id='old',feishu_department_id='old',name='旧部门',sync_quality='complete'));db.flush()
        db.add(Employee(id='u',feishu_user_id='u',name='员工',primary_department_id='old'));db.flush()
        db.add(EmployeeDepartment(employee_id='u',department_id='old'))
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':['missing'],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'u':employee},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Employee,'u').primary_department_id=='old'
        assert db.get(Employee,'u').sync_quality=='pending_verification'
        assert db.get(EmployeeDepartment,('u','old')) is not None


def test_inactive_publication_revokes_session_and_blocks_new_login(sessions):
    from app.persistence.repositories import SqlIdentityRepository
    seed_admin(sessions)
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':[],'status':{'is_resigned':True}})
    Publisher(sessions).publish(Candidate(employees={'u':employee}))
    with sessions() as db: assert db.get(AdminSession,'session').revoked_at is not None
    assert SqlIdentityRepository(sessions,'s'*32).authenticate_session('session',datetime.now()) is None
    service=oauth(sessions);state=service.begin()
    with pytest.raises(ValueError,match='EMPLOYEE_INACTIVE'):service.complete(state,state,'code')


def test_existing_inactive_mapping_blocks_unrevoked_session_but_pending_does_not(sessions):
    from app.persistence.repositories import SqlIdentityRepository
    seed_admin(sessions,'inactive')
    repo=SqlIdentityRepository(sessions,'s'*32)
    assert repo.authenticate_session('session',datetime.now()) is None
    with sessions.begin() as db:
        row=db.get(Employee,'u');row.status='active';row.sync_quality='pending_verification'
    assert repo.authenticate_session('session',datetime.now()) is not None


def test_inactive_revocation_rolls_back_with_publication_failure(sessions,monkeypatch):
    from app.stores.service import StoreAdminService
    seed_admin(sessions)
    def fail(db):
        assert db.get(AdminSession,'session').revoked_at is not None
        raise RuntimeError('injected')
    monkeypatch.setattr(StoreAdminService,'_rebuild_projection',fail)
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':[],'status':{'is_resigned':True}})
    with pytest.raises(RuntimeError):Publisher(sessions).publish(Candidate(employees={'u':employee}))
    with sessions() as db:
        assert db.get(Employee,'u').status=='active'
        assert db.get(AdminSession,'session').revoked_at is None
        assert db.get(DatasetState,1).data_version==1


def test_coverage_reacceptance_records_evidence_clears_marker_and_queues_atomically(sessions):
    from app.sync.coverage import CoverageService
    with sessions.begin() as db: db.add(SystemSetting(key='coverage_invalidated',value='true'))
    service=CoverageService(sessions)
    result=service.accept('验收记录-2026-09','operator:ops',True,True)
    with sessions() as db:
        assert db.get(SystemSetting,'coverage_invalidated') is None
        assert json.loads(db.get(SystemSetting,'coverage_acceptance').value)['reference']=='验收记录-2026-09'
        assert db.get(SyncJob,result['job_id']).type=='reconcile'
        assert db.get(DatasetState,1).coverage_status!='complete'
        assert list(db.scalars(select(ChangeLog)))[-1].object_id=='coverage_acceptance'
    assert service.verified() is True


def test_database_error_and_framework_routes_use_safe_json():
    from app.main import app
    from app.dependencies import get_public_identity,get_read_service
    class Reads:
        def status(self): raise OperationalError('SELECT secret',{'password':'sensitive'},Exception('sensitive'))
    app.dependency_overrides[get_public_identity]=lambda: object()
    app.dependency_overrides[get_read_service]=lambda: Reads()
    try:
        client=TestClient(app,raise_server_exceptions=False)
        response=client.get('/api/v1/status')
        assert response.status_code==503
        assert response.json()['error']['code']=='DATABASE_UNAVAILABLE'
        assert 'sensitive' not in response.text and 'SELECT' not in response.text
        for response in (client.get('/nonexistent'),client.post('/health/live')):
            assert response.status_code in (404,405)
            assert 'error' in response.json()
    finally:app.dependency_overrides.clear()


def test_engine_hides_query_parameters_without_opening_database():
    from app.persistence.database import create_mysql_engine
    engine=create_mysql_engine('mysql+pymysql://unused:unused@localhost/unused')
    try: assert engine.hide_parameters is True
    finally:engine.dispose()


def test_missing_field_error_code_survives_worker_failure(sessions):
    from app.sync.worker import Worker,utcnow
    from app.persistence.repositories import SqlSyncJobRepository
    with sessions.begin() as db: db.add(WorkerLease(id=1,generation=0))
    job,_=SqlSyncJobRepository(sessions).submit('full',None,'test',utcnow())
    worker=Worker(sessions,None);worker.acquire(utcnow())
    job=worker.jobs.claim_next(utcnow(),utcnow()+timedelta(minutes=2))
    worker._fail_job(job,RuntimeError('FEISHU_PARENT_UNREADABLE'))
    with sessions() as db: assert db.get(SyncJob,job.id).error_code=='FEISHU_PARENT_UNREADABLE'


def test_coverage_audit_failure_rolls_back_marker_evidence_and_queue(sessions):
    from app.sync.coverage import CoverageService
    with sessions.begin() as db: db.add(SystemSetting(key='coverage_invalidated',value='true'))
    def reject_audit(mapper,connection,target):
        if target.object_id=='coverage_acceptance': raise RuntimeError('audit-failed')
    event.listen(ChangeLog,'before_insert',reject_audit)
    try:
        with pytest.raises(RuntimeError,match='audit-failed'): CoverageService(sessions).accept('evidence','operator',True,True)
    finally:event.remove(ChangeLog,'before_insert',reject_audit)
    with sessions() as db:
        assert db.get(SystemSetting,'coverage_invalidated') is not None
        assert db.get(SystemSetting,'coverage_acceptance') is None
        assert list(db.scalars(select(SyncJob)))==[]


def test_pending_employee_publishes_after_authoritative_ancestor_resolution(sessions):
    from app.persistence.models import PendingFact
    employee=normalize_user({'user_id':'u','name':'员工','department_ids':['a'],'status':{'is_resigned':False}})
    Publisher(sessions).publish(Candidate(employees={'u':employee},pending=[('department','a')]))
    department={'id':'a','feishu_department_id':'a','parent_id':None,'name':'已确认部门','status':'active','sync_quality':'complete','is_virtual_root':False}
    Publisher(sessions).publish(Candidate(departments={'a':department},employees={'u':employee}))
    with sessions() as db:
        assert db.get(Department,'a').name=='已确认部门'
        assert db.get(EmployeeDepartment,('u','a')) is not None
        assert list(db.scalars(select(PendingFact)))==[]


def test_coverage_cli_uses_bound_config_and_outputs_queued_job(sessions,monkeypatch,capsys):
    from app.sync.coverage import main
    monkeypatch.setattr('app.dependencies.get_runtime',lambda:SimpleNamespace(sessions=sessions))
    monkeypatch.setattr('app.config.get_settings',lambda:Settings(feishu_app_id='a',feishu_tenant_key='t'))
    main(['--reference','accepted-2026','--actor','ops','--all-members-verified','--departmentless-verified'])
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='queued'
    with sessions() as db: assert db.get(SyncJob,output['job_id']) is not None


def test_old_collection_cannot_restore_complete_after_new_acceptance(sessions):
    from app.sync.coverage import CoverageService
    CoverageService(sessions).accept('new-evidence','ops',True,True)
    candidate=Candidate(full=True,coverage_status='complete')
    Publisher(sessions).publish(candidate)
    with sessions() as db: assert db.get(DatasetState,1).coverage_status=='unknown'


def test_new_verified_collection_can_restore_complete(sessions):
    from app.sync.coverage import CoverageService
    CoverageService(sessions).accept('new-evidence','ops',True,True)
    Publisher(sessions).publish(Candidate(full=True,coverage_status='complete',collection_started_at=datetime.now(timezone.utc).isoformat()))
    with sessions() as db: assert db.get(DatasetState,1).coverage_status=='complete'


def test_existing_department_with_unknown_new_parent_retains_fact_and_projects_unknown(sessions):
    with sessions.begin() as db:
        db.add(Department(id='a',feishu_department_id='a',name='真实部门',sync_quality='complete'));db.flush()
        db.add(Employee(id='u',feishu_user_id='u',name='员工',primary_department_id='a',sync_quality='complete'));db.flush()
        db.add(EmployeeDepartment(employee_id='u',department_id='a'))
    department={'id':'a','feishu_department_id':'a','parent_id':'missing','name':'改名部门','status':'active','sync_quality':'complete','is_virtual_root':False}
    Publisher(sessions).publish(Candidate(departments={'a':department},pending=[('department','missing')]))
    with sessions() as db:
        assert db.get(Department,'a').name=='真实部门'
        assert db.get(Department,'a').parent_id is None
        assert db.get(Employee,'u').primary_store_status=='unknown'

```
