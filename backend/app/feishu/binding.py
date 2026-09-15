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
