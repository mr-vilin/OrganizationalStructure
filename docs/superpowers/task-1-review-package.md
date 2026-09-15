# Task 1 review package
基线为空应用目录；以下为本任务新建文件的完整内容（未建立 Git 仓库）。

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
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.dependencies import Runtime, get_admin_identity, get_runtime, require_admin_write
from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, StoreProfile
from app.stores.domain import InvalidStoreChanges, StorePatch
from app.stores.service import StoreAdminService


router = APIRouter(prefix="/admin/api")


@router.get("/status")
def admin_status(identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    data, meta = runtime.reads.status()
    return {"data": data, "meta": meta}


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


class StoreChange(BaseModel):
    department_id: str
    is_store: bool
    store_code: str | None = Field(default=None, max_length=128)
    notes: str | None = None


class StoreBatch(BaseModel):
    data_version: int
    changes: list[StoreChange] = Field(min_length=1, max_length=500)


def _patches(body: StoreBatch) -> list[StorePatch]:
    return [StorePatch(**change.model_dump()) for change in body.changes]


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
def change_logs(object_type: str | None = None, object_id: str | None = None, source: str | None = None, job_id: str | None = None, limit: int = Query(100, ge=1, le=500), cursor: int | None = None, identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    with runtime.sessions() as db:
        stmt = select(ChangeLog).order_by(ChangeLog.id.desc()).limit(limit + 1)
        for column, value in ((ChangeLog.object_type, object_type), (ChangeLog.object_id, object_id), (ChangeLog.source, source), (ChangeLog.job_id, job_id)):
            if value is not None:
                stmt = stmt.where(column == value)
        if cursor is not None:
            stmt = stmt.where(ChangeLog.id < cursor)
        rows = list(db.scalars(stmt))
        page = rows[:limit]
        data = [{"id": row.id, "object_type": row.object_type, "object_id": row.object_id, "source": row.source, "actor": row.actor, "job_id": row.job_id, "before": row.before_data, "after": row.after_data, "committed_at": row.committed_at} for row in page]
        return {"data": data, "meta": {"next_cursor": page[-1].id if len(rows) > limit else None}}


class AllowlistEntry(BaseModel):
    open_id: str


@router.get("/admin-allowlist")
def list_allowlist(identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    with runtime.sessions() as db:
        rows = list(db.scalars(select(AdminAllowlist).order_by(AdminAllowlist.open_id)))
        return {"data": [{"open_id": row.open_id, "created_at": row.created_at} for row in rows], "meta": {}}


@router.post("/admin-allowlist", status_code=201)
def add_allowlist(body: AllowlistEntry, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with runtime.sessions.begin() as db:
        if db.get(AdminAllowlist, body.open_id) is None:
            db.add(AdminAllowlist(open_id=body.open_id, created_at=now))
    return {"data": {"open_id": body.open_id, "created_at": now}, "meta": {}}


@router.delete("/admin-allowlist/{open_id}")
def delete_allowlist(open_id: str, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with runtime.sessions.begin() as db:
        record = db.get(AdminAllowlist, open_id)
        if record is None:
            raise HTTPException(404, {"code": "ADMIN_NOT_FOUND", "message": "管理员不在白名单中"})
        db.execute(update(AdminSession).where(AdminSession.open_id == open_id, AdminSession.revoked_at.is_(None)).values(revoked_at=now))
        db.delete(record)
    return {"data": {"open_id": open_id, "deleted": True}, "meta": {}}


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.get("/api-clients")
def list_clients(identity=Depends(get_admin_identity), runtime: Runtime = Depends(get_runtime)):
    with runtime.sessions() as db:
        rows = list(db.scalars(select(ApiClient).order_by(ApiClient.created_at, ApiClient.id)))
        return {"data": [{"client_id": row.id, "name": row.name, "created_at": row.created_at, "revoked_at": row.revoked_at} for row in rows], "meta": {}}


@router.post("/api-clients", status_code=201)
def create_client(body: ClientCreate, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    record, secret = runtime.identities.issue_api_key(body.name, datetime.now(timezone.utc).replace(tzinfo=None))
    return {"data": {"client_id": record.id, "name": record.name, "secret": secret, "created_at": record.created_at}, "meta": {"secret_shown_once": True}}


@router.post("/api-clients/{client_id}/rotate")
def rotate_client(client_id: str, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with runtime.sessions() as db:
        previous = db.get(ApiClient, client_id)
        if previous is None:
            raise HTTPException(404, {"code": "API_CLIENT_NOT_FOUND", "message": "API 客户端不存在"})
        name = previous.name
    runtime.identities.revoke_api_key(client_id, now)
    record, secret = runtime.identities.issue_api_key(name, now)
    return {"data": {"client_id": record.id, "name": record.name, "secret": secret, "created_at": record.created_at}, "meta": {"secret_shown_once": True, "replaces_client_id": client_id}}


@router.post("/api-clients/{client_id}/revoke")
def revoke_client(client_id: str, authorization=Depends(require_admin_write), runtime: Runtime = Depends(get_runtime)):
    if not runtime.identities.revoke_api_key(client_id, datetime.now(timezone.utc).replace(tzinfo=None)):
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
    initial_admin_open_ids: str = ""

    @property
    def admin_open_ids(self) -> set[str]:
        return {value.strip() for value in self.initial_admin_open_ids.split(",") if value.strip()}

    @property
    def identity_ready(self) -> bool:
        return all((self.session_secret, self.feishu_app_id, self.feishu_app_secret, self.feishu_redirect_uri))


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


@dataclass(frozen=True)
class Employee:
    id: str
    status: str
    primary_department_id: str | None


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

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
    return error(detail.get("code", "HTTP_ERROR"), detail.get("message", "请求失败"), exc.status_code, fields=detail.get("fields"))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    fields = [{"loc": item.get("loc"), "type": item.get("type"), "msg": item.get("msg")} for item in exc.errors()]
    return error("VALIDATION_ERROR", "请求参数无效", 422, fields=fields)


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    if str(exc) == "INITIALIZATION_INCOMPLETE":
        return error("INITIALIZATION_INCOMPLETE", "组织数据尚未完成初始化", 503)
    if str(exc) == "DATASET_CHANGED":
        return error("DATASET_CHANGED", "读取期间数据版本已变化，请重新开始分页", 409)
    if str(exc) == "INVALID_CURSOR":
        return error("INVALID_CURSOR", "分页游标无效或与筛选条件不匹配", 400)
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
def login(settings: Settings = Depends(get_settings)):
    if not settings.identity_ready:
        raise HTTPException(503, {"code": "IDENTITY_NOT_CONFIGURED", "message": "飞书登录尚未配置"})
    raise HTTPException(501, {"code": "OAUTH_ADAPTER_PENDING", "message": "OAuth 适配器尚未接入"})


@app.post("/admin/auth/logout")
def logout(authorization=Depends(require_admin_write), runtime: Runtime | None = Depends(get_runtime)):
    identity, _ = authorization
    runtime.identities.revoke_session(identity.id, datetime.utcnow())
    response = JSONResponse({"data": {"revoked": True}, "meta": {}})
    response.delete_cookie("org_session", httponly=True, secure=True, samesite="lax")
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
def store_employees(store_id: str, membership: str = Query("all", pattern="^(all|primary)$"), include_inactive: bool = False, limit: int = Query(100, ge=1, le=500), cursor: str | None = None, identity=Depends(get_public_identity), service: ReadService = Depends(get_read_service)):
    return _list("list_store_employees", service, store_id=store_id, membership=membership, include_inactive=include_inactive, limit=limit, cursor=cursor)


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
def list_jobs(limit: int = Query(100, ge=1, le=500), status: str | None = None, identity=Depends(get_admin_identity), runtime: Runtime | None = Depends(get_runtime)):
    from sqlalchemy import select
    from .persistence.models import SyncJob
    with runtime.sessions() as db:
        stmt = select(SyncJob).order_by(SyncJob.created_at.desc(), SyncJob.id.desc()).limit(limit)
        if status:
            stmt = stmt.where(SyncJob.status == status)
        rows = list(db.scalars(stmt))
        return {"data": [{"job_id": job.id, "type": job.type, "root_department_id": job.root_department_id, "status": job.status, "phase": job.phase, "attempt": job.attempt, "error_code": job.error_code, "created_at": job.created_at, "updated_at": job.updated_at} for job in rows], "meta": {}}


@app.get("/admin/api/sync/jobs/{job_id}")
def get_job(job_id: str, identity=Depends(get_admin_identity), runtime: Runtime | None = Depends(get_runtime)):
    from sqlalchemy.orm import Session
    from .persistence.models import SyncJob
    with runtime.sessions() as db:
        job = db.get(SyncJob, job_id)
        if job is None:
            raise HTTPException(404, {"code": "JOB_NOT_FOUND", "message": "同步任务不存在"})
        return {"data": {"job_id": job.id, "type": job.type, "root_department_id": job.root_department_id, "status": job.status, "phase": job.phase, "attempt": job.attempt, "error_code": job.error_code}, "meta": {}}


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
    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1800, isolation_level="REPEATABLE READ")


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
            "last_full_sync_at": state.last_full_sync_at,
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
        return {"id": row.id, "parent_id": row.parent_id, "name": row.name, "path": list(reversed(names)), "status": row.status, "sync_quality": row.sync_quality, "is_virtual_root": row.is_virtual_root, "is_store": bool(profile and profile.is_store), "store_code": profile.store_code if profile else None}

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
        return {"id": row.id, "name": row.name, "employee_no": row.employee_no, "status": row.status, "sync_quality": row.sync_quality, "department_ids": memberships, "primary_department_id": row.primary_department_id, "store_ids": [item[0] for item in stores], "primary_store_id": primary_store, "primary_store_status": row.primary_store_status}

```

## backend/app/persistence/repositories.py
```
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import AdminAllowlist, AdminSession, ApiClient, DatasetState, SyncJob, SystemSetting


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
            statement = select(AdminSession).join(AdminAllowlist).where(
                AdminSession.id == session_id,
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > now,
            )
            return db.scalar(statement)

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
            db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
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
                select(SyncJob).where(SyncJob.status == "queued").order_by(SyncJob.created_at, SyncJob.id).limit(1).with_for_update(skip_locked=True)
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


@dataclass(frozen=True)
class StorePatch:
    department_id: str
    is_store: bool
    store_code: str | None = None
    notes: str | None = None


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
        code = change.store_code.strip() if change.store_code and change.store_code.strip() else None
        item = replace(change, store_code=code)
        if department is None:
            errors.append(StoreValidationError(change.department_id, "DEPARTMENT_NOT_FOUND", "部门不存在"))
        elif change.is_store and department["is_virtual_root"]:
            errors.append(StoreValidationError(change.department_id, "VIRTUAL_ROOT", "虚拟根不能设为门店"))
        elif change.is_store and department["status"] != "active":
            errors.append(StoreValidationError(change.department_id, "DEPARTMENT_INACTIVE", "失效部门不能新设为门店"))
        elif code is not None and code in seen_codes:
            errors.append(StoreValidationError(change.department_id, "DUPLICATE_STORE_CODE", "批次内门店编码重复"))
        else:
            if code is not None:
                seen_codes.add(code)
            normalized.append(item)
    if errors and raise_errors:
        raise InvalidStoreChanges(errors)
    return errors if errors else normalized


```

## backend/app/stores/service.py
```
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.directory.domain import Department as DomainDepartment
from app.directory.domain import Employee as DomainEmployee
from app.directory.domain import Membership, resolve_employee_stores
from app.persistence.models import ChangeLog, DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreCodeReservation, StoreProfile

from .domain import InvalidStoreChanges, StorePatch, StoreValidationError, validate_store_changes


class StoreAdminService:
    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def preview(self, changes: list[StorePatch], expected_version: int) -> dict:
        with self._sessions() as db, db.begin():
            state = self._lock_state(db, expected_version, lock=False)
            normalized = self._validate(db, changes)
            affected = db.scalar(select(func.count(func.distinct(EmployeeDepartment.employee_id))).where(EmployeeDepartment.department_id.in_([c.department_id for c in normalized]), EmployeeDepartment.active.is_(True))) or 0
            return {"data_version": state.data_version, "changes": [asdict(c) for c in normalized], "affected_employee_count": affected}

    def apply(self, changes: list[StorePatch], expected_version: int, actor: str, now: datetime) -> dict:
        with self._sessions.begin() as db:
            state = self._lock_state(db, expected_version, lock=True)
            normalized = self._validate(db, changes)
            business_changes = 0
            for change in normalized:
                current = db.get(StoreProfile, change.department_id)
                before = self._snapshot(current)
                after = {"is_store": change.is_store, "store_code": change.store_code, "notes": change.notes}
                if before == after:
                    continue
                if change.store_code:
                    reservation = db.get(StoreCodeReservation, change.store_code)
                    if reservation and reservation.department_id != change.department_id:
                        raise InvalidStoreChanges([StoreValidationError(change.department_id, "STORE_CODE_RESERVED", "门店编码已由其他部门保留")])
                    if reservation is None:
                        db.add(StoreCodeReservation(store_code=change.store_code, department_id=change.department_id, reserved_at=now))
                if current is None:
                    current = StoreProfile(department_id=change.department_id)
                    db.add(current)
                current.is_store, current.store_code, current.notes = change.is_store, change.store_code, change.notes
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
        return validate_store_changes(changes, departments=departments)

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
    def _rebuild_projection(db: Session) -> None:
        departments = {
            row.id: DomainDepartment(row.id, row.parent_id, bool(row.store_profile.is_store) if hasattr(row, "store_profile") and row.store_profile else False, row.status)
            for row in db.scalars(select(Department))
        }
        store_ids = set(db.scalars(select(StoreProfile.department_id).where(StoreProfile.is_store.is_(True))))
        departments = {key: DomainDepartment(value.id, value.parent_id, key in store_ids, value.status) for key, value in departments.items()}
        relations = list(db.scalars(select(EmployeeDepartment)))
        by_employee: dict[str, list[Membership]] = {}
        for relation in relations:
            by_employee.setdefault(relation.employee_id, []).append(Membership(relation.employee_id, relation.department_id, relation.active))
        db.execute(delete(EmployeeStore))
        for employee in db.scalars(select(Employee)):
            result = resolve_employee_stores(DomainEmployee(employee.id, employee.status, employee.primary_department_id), by_employee.get(employee.id, []), departments)
            employee.primary_store_status = result.primary_store_status
            for store_id in result.store_ids:
                db.add(EmployeeStore(employee_id=employee.id, store_id=store_id, is_primary=store_id == result.primary_store_id, path=[]))

```

## backend/app/sync/__init__.py
```
from .services import JobService, SyncJob

__all__ = ["JobService", "SyncJob"]


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

## backend/app/sync/worker.py
```
"""同步 worker 进程入口；Task 2 注入飞书采集与发布处理器。"""

import logging


logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("同步 worker 已启动；等待飞书适配器接入")


if __name__ == "__main__":
    main()


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
"""创建组织目录首版表结构。"""

from alembic import op

from app.persistence.models import Base


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 元数据是首版结构的单一来源；后续迁移必须使用显式增量 DDL。
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=False)

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