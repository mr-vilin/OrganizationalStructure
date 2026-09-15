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
