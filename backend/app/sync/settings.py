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
