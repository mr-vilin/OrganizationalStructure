from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import AgentContext
from .errors import OperationConflict, OperationNotFound
from app.persistence.models import DatasetState, OperationReceipt


_SENSITIVE = ("token", "secret", "password", "credential", "authorization", "api_key")


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if any(x in str(k).lower() for x in _SENSITIVE) else _sanitize(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in value[:100]]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value if not isinstance(value, str) or len(value) <= 2000 else value[:2000]
    return str(value)[:2000]


class ReceiptRepository:
    """OperationReceipt persistence using a caller-owned transaction."""

    def get_by_idempotency(self, db: Session, actor_id: str, environment: str, idempotency_key: str) -> OperationReceipt | None:
        return db.scalar(select(OperationReceipt).where(
            OperationReceipt.actor_id == actor_id,
            OperationReceipt.environment == environment,
            OperationReceipt.idempotency_key == idempotency_key,
        ))

    def create(self, db: Session, context: AgentContext, capability: str, idempotency_key: str, request_hash: str, now: datetime) -> OperationReceipt:
        existing = db.scalar(select(OperationReceipt).where(
            OperationReceipt.actor_id == context.actor_id,
            OperationReceipt.environment == context.environment,
            OperationReceipt.idempotency_key == idempotency_key,
        ).with_for_update())
        if existing is not None:
            if existing.request_hash != request_hash:
                raise OperationConflict()
            return existing
        state = db.scalar(select(DatasetState).where(DatasetState.id == 1).with_for_update())
        if state is None:
            raise OperationConflict()
        receipt = OperationReceipt(
            operation_id=f"op_{uuid4().hex}", idempotency_key=idempotency_key,
            capability=capability, actor_type=context.actor_type, actor_id=context.actor_id,
            environment=context.environment, run_id=context.run_id, case_id=context.case_id,
            request_hash=request_hash, status="recorded", before_epoch=state.dataset_epoch,
            before_version=state.data_version, created_at=now, updated_at=now,
        )
        db.add(receipt)
        db.flush()
        return receipt

    def _get_for_update(self, db: Session, operation_id: str) -> OperationReceipt:
        row = db.scalar(select(OperationReceipt).where(OperationReceipt.operation_id == operation_id).with_for_update())
        if row is None:
            raise OperationNotFound()
        return row

    def mark_accepted(self, db: Session, operation_id: str, job_id: str, epoch: str, version: int, summary: dict[str, Any] | None, now: datetime) -> OperationReceipt:
        row = self._get_for_update(db, operation_id)
        row.status, row.job_id = "accepted", job_id
        row.committed_epoch, row.committed_version = epoch, version
        row.result_summary, row.updated_at = _sanitize(summary or {}), now
        db.flush()
        return row

    def mark_submitted(self, db: Session, operation_id: str, epoch: str, version: int, summary: dict[str, Any] | None, audit_ids: list[int | str] | None, now: datetime) -> OperationReceipt:
        row = self._get_for_update(db, operation_id)
        row.status = "submitted"
        row.committed_epoch, row.committed_version = epoch, version
        result = dict(summary or {})
        if audit_ids is not None:
            result["audit_ids"] = list(audit_ids)
        row.result_summary, row.updated_at = _sanitize(result), now
        db.flush()
        return row

    def mark_failed(self, db: Session, operation_id: str, error_code: str, summary: dict[str, Any] | None, now: datetime) -> OperationReceipt:
        row = self._get_for_update(db, operation_id)
        row.status, row.error_code = "failed", str(error_code)[:64]
        row.result_summary, row.updated_at = _sanitize(summary or {}), now
        db.flush()
        return row
