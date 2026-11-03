
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.dependencies import get_admin_identity, get_runtime, require_admin_write
from app.feishu.client import FeishuClient
from .service import InitializationService

router = APIRouter(prefix='/admin/api/initialization')


def get_initialization_service(runtime=Depends(get_runtime), settings=Depends(get_settings)):
    if runtime is None:
        raise HTTPException(503, {'code': 'DATABASE_NOT_CONFIGURED', 'message': '数据库尚未配置'})
    api = FeishuClient(settings.feishu_app_id, settings.feishu_app_secret.get_secret_value()) if settings.feishu_app_secret else None
    try:
        yield InitializationService(runtime.sessions, settings, api)
    finally:
        if api:
            api.http.close()


class Mappings(BaseModel):
    permission_role: str = Field(min_length=1, max_length=191)
    store_attribute: str = Field(min_length=1, max_length=191)
    employee_type_options: dict[str, str]


@router.get('')
def status(identity=Depends(get_admin_identity), service=Depends(get_initialization_service)):
    return {'data': service.status(), 'meta': {}}


@router.put('/settings')
def configure(body: Mappings, authorization=Depends(require_admin_write), service=Depends(get_initialization_service)):
    return {'data': service.configure(body.model_dump(), f'admin:{authorization[0].open_id}'), 'meta': {}}


@router.post('/checks/{step}')
def run_check(step: int, authorization=Depends(require_admin_write), service=Depends(get_initialization_service)):
    if not 1 <= step <= 4:
        raise HTTPException(422, {'code': 'INVALID_INITIALIZATION_STEP', 'message': '初始化检查步骤无效'})
    return {'data': service.run_check(step, f'admin:{authorization[0].open_id}'), 'meta': {}}


@router.post('/start', status_code=202)
def start(authorization=Depends(require_admin_write), service=Depends(get_initialization_service)):
    return {'data': {'job_id': service.start(f'admin:{authorization[0].open_id}')}, 'meta': {}}


@router.post('/restart')
def restart(authorization=Depends(require_admin_write), service=Depends(get_initialization_service)):
    return {'data': service.restart(f'admin:{authorization[0].open_id}'), 'meta': {}}
