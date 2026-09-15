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
