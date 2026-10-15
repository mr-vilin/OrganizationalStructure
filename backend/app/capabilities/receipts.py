from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import AgentContext
from .errors import OperationConflict, OperationNotFound
from app.persistence.models import ChangeLog, DatasetState, OperationReceipt, SyncJob


_SENSITIVE = ('token', 'secret', 'password', 'credential', 'authorization', 'api_key')
# 只允许业务标识与计数等结构化证据；外部消息、URL、异常文本一律不持久化。
_SAFE_IDS = {'job_id', 'operation_id', 'object_id', 'department_id', 'store_id'}
_SAFE_ENUMS = {'status', 'object_type', 'error_code'}
_IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,191}\Z')
_ERROR_CODE = re.compile(r'[A-Z][A-Z0-9_]{0,63}\Z')


def _sanitize(value: Any, depth: int = 0, field: str = '') -> Any:
    if depth > 4:
        return '[TRUNCATED]'
    if isinstance(value, dict):
        return {
            str(k): ('[REDACTED]' if any(x in str(k).lower() for x in _SENSITIVE)
                     else _sanitize(v, depth + 1, str(k)))
            for k, v in value.items()
            # 自定义键可能包含外部文本，保留结构化键而不保存原文键名。
            if re.fullmatch(r'[a-z][a-z0-9_]{0,63}', str(k))
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1, field) for v in value[:100]]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str) and field in _SAFE_IDS | _SAFE_ENUMS and _IDENTIFIER.fullmatch(value):
        return value
    return '[REDACTED]'


def _audit_ids(values: list[int | str] | None) -> list[int | str] | None:
    if values is None:
        return None
    # 审计关联独立校验并完整保存，不应用展示摘要的长度截断规则。
    if any(not ((type(v) is int and v >= 0) or (type(v) is str and _IDENTIFIER.fullmatch(v))) for v in values):
        raise OperationConflict()
    return list(values)


class ReceiptRepository:
    """使用调用方事务；所有写入统一先锁 DatasetState，再锁回执。"""

    def get_by_idempotency(self, db: Session, actor_id: str, environment: str, idempotency_key: str) -> OperationReceipt | None:
        return db.scalar(select(OperationReceipt).where(
            OperationReceipt.actor_id == actor_id,
            OperationReceipt.environment == environment,
            OperationReceipt.idempotency_key == idempotency_key,
        ))

    def _lock_state(self, db: Session) -> DatasetState:
        state = db.scalar(select(DatasetState).where(DatasetState.id == 1)
                          .with_for_update().execution_options(populate_existing=True))
        if state is None:
            raise OperationConflict()
        return state

    def create(self, db: Session, context: AgentContext, capability: str, idempotency_key: str, request_hash: str, now: datetime) -> OperationReceipt:
        # 存在的固定行充当创建锁，避免对不存在键加锁的竞态及间隙锁升级死锁。
        # MySQL FOR UPDATE 使用当前读，锁等待结束后能看到获胜事务提交的回执。
        state = self._lock_state(db)
        existing = db.scalar(select(OperationReceipt).where(
            OperationReceipt.actor_id == context.actor_id,
            OperationReceipt.environment == context.environment,
            OperationReceipt.idempotency_key == idempotency_key,
        ).with_for_update().execution_options(populate_existing=True))
        if existing is not None:
            if existing.request_hash != request_hash:
                raise OperationConflict()
            return existing
        receipt = OperationReceipt(
            operation_id=f'op_{uuid4().hex}', idempotency_key=idempotency_key,
            capability=capability, actor_type=context.actor_type, actor_id=context.actor_id,
            environment=context.environment, run_id=context.run_id, case_id=context.case_id,
            request_hash=request_hash, status='recorded', before_epoch=state.dataset_epoch,
            before_version=state.data_version, created_at=now, updated_at=now,
        )
        db.add(receipt)
        db.flush()
        return receipt

    def _get_for_update(self, db: Session, operation_id: str) -> OperationReceipt:
        self._lock_state(db)
        row = db.scalar(select(OperationReceipt).where(OperationReceipt.operation_id == operation_id)
                        .with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise OperationNotFound()
        return row

    def _update(self, db: Session, row: OperationReceipt, status: str, values: dict[str, Any], now: datetime) -> OperationReceipt:
        if 'committed_version' in values:
            epoch, version = values['committed_epoch'], values['committed_version']
            if not epoch or type(version) is not int or version < 0:
                raise OperationConflict()
            for previous_epoch, previous_version in (
                (row.before_epoch, row.before_version),
                (row.committed_epoch, row.committed_version),
            ):
                if epoch == previous_epoch and previous_version is not None and version < previous_version:
                    raise OperationConflict()
        # 已接受请求不再重绑任务；完成后只允许完全相同结果的幂等重放。
        if row.status == status:
            if any(getattr(row, key) != value for key, value in values.items()):
                raise OperationConflict()
            return row
        allowed = {'recorded': {'accepted', 'submitted', 'failed'}, 'accepted': {'submitted', 'failed'}}
        if status not in allowed.get(row.status, set()):
            raise OperationConflict()
        for key, value in values.items():
            setattr(row, key, value)
        row.status, row.updated_at = status, now
        db.flush()
        return row

    def mark_accepted(self, db: Session, operation_id: str, job_id: str, epoch: str, version: int, summary: dict[str, Any] | None, now: datetime) -> OperationReceipt:
        row = self._get_for_update(db, operation_id)
        return self._update(db, row, 'accepted', {
            'job_id': job_id, 'committed_epoch': epoch, 'committed_version': version,
            'result_summary': _sanitize(summary or {}), 'error_code': None,
        }, now)

    def mark_submitted(self, db: Session, operation_id: str, epoch: str, version: int, summary: dict[str, Any] | None, audit_ids: list[int | str] | None, now: datetime) -> OperationReceipt:
        result = _sanitize({k: v for k, v in (summary or {}).items() if k != 'audit_ids'})
        validated_ids = _audit_ids(audit_ids)
        if validated_ids is not None:
            result['audit_ids'] = validated_ids
        row = self._get_for_update(db, operation_id)
        return self._update(db, row, 'submitted', {
            'committed_epoch': epoch, 'committed_version': version,
            'result_summary': result, 'error_code': None,
        }, now)

    def mark_failed(self, db: Session, operation_id: str, error_code: str, summary: dict[str, Any] | None, now: datetime) -> OperationReceipt:
        if not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code):
            raise OperationConflict()
        row = self._get_for_update(db, operation_id)
        return self._update(db, row, 'failed', {
            'error_code': error_code, 'result_summary': _sanitize(summary or {}),
        }, now)

    def finalize_job_in_session(self, db: Session, job: SyncJob, now: datetime, *, changed_count: int | None = None, allow_initial_epoch_transition: bool = False) -> None:
        """调用方已按 DatasetState → job 顺序锁定任务；只收束 accepted 回执。"""
        if job.status not in {'succeeded', 'failed'}:
            raise OperationConflict()
        db.flush()
        state = self._lock_state(db)
        rows = list(db.scalars(select(OperationReceipt).where(
            OperationReceipt.job_id == job.id, OperationReceipt.status == 'accepted',
        ).order_by(OperationReceipt.operation_id).with_for_update().execution_options(populate_existing=True)))
        summary = {'job_id': job.id, 'status': job.status,
                   'success_count': job.success_count, 'failure_count': job.failure_count}
        if changed_count is not None:
            summary['changed_count'] = changed_count
        audit_ids = list(db.scalars(select(ChangeLog.id).where(ChangeLog.job_id == job.id).order_by(ChangeLog.id)))
        for row in rows:
            same_epoch = row.before_epoch == row.committed_epoch == state.dataset_epoch
            first_epoch = (allow_initial_epoch_transition and state.dataset_epoch != 'pending'
                           and row.before_epoch == row.committed_epoch == 'pending')
            if not (same_epoch or first_epoch):
                self._update(db, row, 'failed', {
                    'error_code': 'DATASET_CHANGED', 'result_summary': _sanitize({'job_id': job.id}),
                }, now)
                continue
            if job.status == 'failed':
                code = job.error_code
                if not isinstance(code, str) or not _ERROR_CODE.fullmatch(code):
                    code = 'SYNC_FAILED'
                self._update(db, row, 'failed', {
                    'error_code': code, 'result_summary': _sanitize(summary),
                }, now)
                continue
            self._update(db, row, 'submitted', {
                'committed_epoch': state.dataset_epoch, 'committed_version': state.data_version,
                'result_summary': {**_sanitize(summary), 'audit_ids': _audit_ids(audit_ids)},
                'error_code': None,
            }, now)
