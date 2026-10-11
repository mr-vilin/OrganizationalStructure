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


def custom_attrs(sessions):
    with sessions() as db:
        row = db.scalar(select(FeishuConnection).where(FeishuConnection.id == 1))
        return dict(row.custom_attrs or {}) if row else {}


def put_custom_attrs(sessions, value):
    if not isinstance(value, dict):
        raise ValueError('VALIDATION_ERROR')
    allowed = {'permission_role', 'store_attribute', 'employee_type_options'}
    if set(value) - allowed:
        raise ValueError('VALIDATION_ERROR')
    for key in ('permission_role', 'store_attribute'):
        if key in value and value[key] is not None and (not isinstance(value[key], str) or not value[key].strip()):
            raise ValueError('VALIDATION_ERROR')
    with sessions.begin() as db:
        row = db.scalar(select(FeishuConnection).where(FeishuConnection.id == 1).with_for_update())
        if row is None:
            raise RuntimeError('CONFIG_BINDING_MISSING')
        row.custom_attrs = {**(row.custom_attrs or {}), **value}
        return dict(row.custom_attrs)
