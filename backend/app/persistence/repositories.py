import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.capabilities.receipts import ReceiptRepository

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
                # 恢复/人工清理后标记可能丢失，但白名单记录仍在；避免重复主键导致登录失败。
                if db.get(AdminAllowlist, open_id) is None:
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

    def submit(self, job_type: str, root_department_id: str | None, requested_by: str, now: datetime, description: str | None = None) -> tuple[SyncJob, bool]:
        with self._sessions.begin() as db:
            return self.submit_in_session(db, job_type, root_department_id, requested_by, now, description)

    @staticmethod
    def _lock_dataset(db: Session) -> DatasetState:
        # 与回执和 Publisher 共用 DatasetState → 队列锁（如需）→ 任务 → 回执顺序。
        state = db.scalar(select(DatasetState).where(DatasetState.id == 1)
                          .with_for_update().execution_options(populate_existing=True))
        if state is None:
            raise RuntimeError("DATABASE_SCHEMA_INCOMPLETE")
        return state

    def submit_in_session(self, db: Session, job_type: str, root_department_id: str | None, requested_by: str, now: datetime, description: str | None = None) -> tuple[SyncJob, bool]:
        self._lock_dataset(db)
        lock_row = db.scalar(select(SystemSetting).where(SystemSetting.key == "task_queue_lock").with_for_update().execution_options(populate_existing=True))
        if lock_row is None:
            raise RuntimeError("DATABASE_SCHEMA_INCOMPLETE")
        existing = db.scalar(
            select(SyncJob).where(
                SyncJob.type == job_type,
                SyncJob.root_department_id.is_(None) if root_department_id is None else SyncJob.root_department_id == root_department_id,
                SyncJob.status.in_(self.ACTIVE),
            ).with_for_update().execution_options(populate_existing=True)
        )
        if existing is not None:
            return existing, True
        job = SyncJob(
            id=secrets.token_urlsafe(12), type=job_type, root_department_id=root_department_id,
            name=f"{job_type}同步", trigger_source='manual' if requested_by.startswith('admin:') else requested_by,
            description=description or ('指定部门子树同步' if root_department_id else '全量组织同步'), requested_by=requested_by,
            status="queued", attempt=1, lease_generation=0, execution_count=0, retry_count=0,
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
            job.execution_count = (job.execution_count or 0) + 1
            job.started_at = now
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
            self._lock_dataset(db)
            job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update().execution_options(populate_existing=True))
            if job is None or job.status != "running" or job.lease_generation != lease_generation:
                raise ValueError("job lease is stale")
            job.status, job.error_code, job.error_detail = status, error_code, error_detail
            job.lease_expires_at, job.updated_at = None, now
            job.finished_at = now
            ReceiptRepository().finalize_job_in_session(db, job, now)
            return job

    def retry(self, job_id: str, requested_by: str, now: datetime) -> SyncJob:
        with self._sessions.begin() as db:
            return self.retry_in_session(db, job_id, requested_by, now)

    def retry_in_session(self, db: Session, job_id: str, requested_by: str, now: datetime) -> SyncJob:
        self._lock_dataset(db)
        job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update().execution_options(populate_existing=True))
        if job is None or job.status != "failed":
            raise ValueError("only failed jobs can be retried")
        job.status, job.requested_by, job.attempt = "queued", requested_by, job.attempt + 1
        job.retry_count = (job.retry_count or 0) + 1
        job.finished_at = None
        job.started_at = None
        job.phase = 'queued'
        db.add(ChangeLog(object_type='sync_job', object_id=job.id, source='admin', actor=requested_by, job_id=job.id, before_data={'status': 'failed', 'attempt': job.attempt - 1}, after_data={'status': 'queued', 'attempt': job.attempt, 'retry_count': job.retry_count}, committed_at=now))
        job.error_code = job.error_detail = None
        job.updated_at = now
        return job
