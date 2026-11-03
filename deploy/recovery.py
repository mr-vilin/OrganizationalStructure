"""备份导入后、所有应用进程停止期间重置安全与数据世代。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select, update

from app.config import get_settings
from app.persistence.database import create_mysql_engine, session_factory
from app.persistence.models import AdminAllowlist, AdminSession, ApiClient, ChangeLog, DatasetState, EventInbox, SyncJob, SystemSetting


def reset_restored_state(sessions, *, actor: str, admin_open_id: str | None = None) -> str:
    from app.persistence.models import OAuthState, WorkerLease
    now = datetime.now(timezone.utc)
    new_epoch = str(uuid4())
    with sessions.begin() as session:
        state = session.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
        if state is None:
            raise RuntimeError('数据库迁移尚未完成，无法重置恢复状态')
        old_epoch = state.dataset_epoch
        state.dataset_epoch = new_epoch
        state.data_version = 0
        state.initialization_status = 'pending'
        state.coverage_status = 'unknown'
        state.last_full_sync_at = None
        from app.initialization.service import save_flow
        save_flow(session, {'flow_id': uuid4().hex, 'phase': 'cleanup_required', 'checks': [], 'evidence': None})
        session.execute(update(AdminSession).where(AdminSession.revoked_at.is_(None)).values(revoked_at=now))
        session.execute(update(ApiClient).where(ApiClient.revoked_at.is_(None)).values(revoked_at=now))
        session.execute(update(SyncJob).where(SyncJob.status.in_(['queued', 'running'])).values(
            status='failed', error_code='RESTORE_REQUIRES_RECONCILIATION', error_detail=None,
            lease_generation=SyncJob.lease_generation + 1, lease_expires_at=None, updated_at=now))
        session.execute(update(EventInbox).where(EventInbox.status.in_(['queued', 'failed', 'running'])).values(status='ignored_restored'))
        session.execute(delete(OAuthState))
        session.execute(update(WorkerLease).values(owner=None, expires_at=None, generation=WorkerLease.generation + 1))
        session.execute(delete(SystemSetting).where(SystemSetting.key == 'reconcile_last_day'))
        if admin_open_id and session.get(AdminAllowlist, admin_open_id) is None:
            session.add(AdminAllowlist(open_id=admin_open_id, created_at=now))
            session.add(ChangeLog(object_type='admin_allowlist', object_id=admin_open_id, source='recovery',
                                  actor=actor, before_data=None, after_data={'open_id': admin_open_id}, committed_at=now))
        session.add(ChangeLog(object_type='dataset', object_id='1', source='recovery', actor=actor,
                              before_data={'dataset_epoch': old_epoch},
                              after_data={'dataset_epoch': new_epoch, 'initialization_status': 'pending',
                                          'sessions_revoked': True, 'api_clients_revoked': True}, committed_at=now))
    return new_epoch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-stopped', action='store_true', required=True,
                        help='确认 HTTP、worker 和长连接进程均已停止')
    parser.add_argument('--actor', required=True, help='恢复操作责任人标识，写入审计')
    parser.add_argument('--admin-open-id', help='可选：经线下核验的同应用恢复管理员 open_id，明确添加到白名单')
    args = parser.parse_args()
    if not args.actor.strip() or len(args.actor) > 255:
        parser.error('actor 必须是 1～255 个字符')
    if args.admin_open_id and (not args.admin_open_id.startswith('ou_') or len(args.admin_open_id) > 191):
        parser.error('恢复管理员必须是同应用的 ou_ 开头 open_id')
    settings = get_settings()
    if not settings.database_url:
        parser.error('未配置 ORG_DATABASE_URL')
    engine = create_mysql_engine(settings.database_url)
    try:
        epoch = reset_restored_state(session_factory(engine), actor=args.actor.strip(), admin_open_id=args.admin_open_id)
        print(f'恢复世代已重置：{epoch}；启动应用后由管理员在向导中重新初始化，再创建只读客户端凭据。')
    finally:
        engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
