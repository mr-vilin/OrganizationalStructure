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
    note: str | None = None


@app.post("/admin/api/sync/jobs", status_code=202)
def submit_job(body: JobRequest, authorization=Depends(require_admin_write), runtime: Runtime | None = Depends(get_runtime)):
    from datetime import datetime, timezone
    if body.type not in {"initialize", "full", "subtree", "reconcile"} or (body.type == "subtree" and not body.root_department_id):
        raise HTTPException(422, {"code": "INVALID_JOB_SCOPE", "message": "同步任务类型或范围无效"})
    identity, _ = authorization
    job, reused = runtime.jobs.submit(body.type, body.root_department_id, f"admin:{identity.open_id}", datetime.now(timezone.utc), body.note)
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
