import secrets
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True)
class SyncJob:
    job_id: str
    type: str
    root_department_id: str | None
    requested_by: str
    status: str
    attempt: int
    created_at: datetime
    reused: bool = False
    error_code: str | None = None


class JobService:
    """任务领域服务；持久仓储可在 Task 2 worker 接入时替换。"""

    def __init__(self):
        self._jobs: dict[str, SyncJob] = {}

    def submit(self, type: str, root_department_id: str | None, requested_by: str, now: datetime) -> SyncJob:
        for job in self._jobs.values():
            if job.type == type and job.root_department_id == root_department_id and job.status in {"queued", "running"}:
                return replace(job, reused=True)
        job = SyncJob(secrets.token_urlsafe(12), type, root_department_id, requested_by, "queued", 1, now)
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> SyncJob | None:
        return self._jobs.get(job_id)

    def claim(self, job_id: str) -> SyncJob:
        return self._transition(job_id, "running")

    def complete(self, job_id: str) -> SyncJob:
        return self._transition(job_id, "succeeded")

    def fail(self, job_id: str, error_code: str, now: datetime) -> SyncJob:
        job = replace(self._jobs[job_id], status="failed", error_code=error_code)
        self._jobs[job_id] = job
        return job

    def retry(self, job_id: str, requested_by: str, now: datetime) -> SyncJob:
        previous = self._jobs[job_id]
        if previous.status != "failed":
            raise ValueError("only failed jobs can be retried")
        job = replace(previous, status="queued", requested_by=requested_by, attempt=previous.attempt + 1, error_code=None, reused=False)
        self._jobs[job_id] = job
        return job

    def _transition(self, job_id: str, status: str) -> SyncJob:
        job = replace(self._jobs[job_id], status=status)
        self._jobs[job_id] = job
        return job
