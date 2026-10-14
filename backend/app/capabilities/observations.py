from __future__ import annotations

from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .contracts import Observation
from app.persistence.models import DatasetState, PendingFact, SyncJob, SyncJobDetail


_STATUS_EXECUTION = {"queued": "accepted", "accepted": "accepted", "running": "running", "succeeded": "submitted", "submitted": "submitted", "failed": "failed"}


class ObservationService:
    def _state(self, db: Session) -> DatasetState:
        return db.scalar(select(DatasetState).where(DatasetState.id == 1))

    def _base(self, db: Session, execution: str, evidence: dict[str, Any] | None = None, *, fact_quality: str | None = None) -> Observation:
        state = self._state(db)
        pending = db.scalar(select(func.count()).select_from(PendingFact)) or 0
        quality = fact_quality or ("partial" if pending else "resolved")
        if state is None:
            return Observation("unconfirmed", "unknown", None, None, "retry_observation", evidence or {})
        if pending and execution in {"submitted", "verified"}:
            execution = "partial"
        return Observation(execution, quality, state.dataset_epoch, state.data_version, None if execution in {"submitted", "verified", "failed", "partial"} else "wait_for_completion", evidence or {})

    def observation_for_status(self, db: Session, status: str, job_id: str | None = None) -> Observation:
        try:
            execution = _STATUS_EXECUTION.get(status)
            if execution is None:
                return Observation("unconfirmed", "unknown", None, None, "inspect_status", {"status": "unknown"})
            evidence: dict[str, Any] = {"status": status}
            if job_id:
                evidence["job_id"] = job_id
                failed = db.scalar(select(func.count()).select_from(SyncJobDetail).where(SyncJobDetail.job_id == job_id, SyncJobDetail.status == "failed")) or 0
                if failed:
                    evidence["failed_detail_count"] = failed
                    execution = "partial" if execution == "submitted" else execution
            return self._base(db, execution, evidence, fact_quality="partial" if execution == "partial" else None)
        except Exception:
            return Observation("unconfirmed", "unknown", None, None, "retry_observation", {"status": "unavailable"})

    def observation_for_job(self, db: Session, job_id: str) -> Observation:
        try:
            job = db.get(SyncJob, job_id)
            if job is None:
                return Observation("unconfirmed", "unknown", None, None, "inspect_job", {"job_id": job_id, "status": "missing"})
            return self.observation_for_status(db, job.status, job_id)
        except Exception:
            return Observation("unconfirmed", "unknown", None, None, "retry_observation", {"job_id": job_id, "status": "unavailable"})

    def observation_for_commit(self, db: Session, epoch: str | None = None, version: int | None = None, job_id: str | None = None) -> Observation:
        try:
            obs = self.observation_for_job(db, job_id) if job_id else self._base(db, "submitted", {"status": "committed"})
            if epoch is not None and obs.dataset_epoch != epoch or version is not None and obs.data_version != version:
                return Observation("unconfirmed", "inconsistent", obs.dataset_epoch, obs.data_version, "refresh_dataset", {**obs.evidence, "expected_epoch": epoch, "expected_version": version})
            return obs
        except Exception:
            return Observation("unconfirmed", "unknown", None, None, "retry_observation", {"status": "unavailable"})
