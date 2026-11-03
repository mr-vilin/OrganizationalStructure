"""Organization capabilities with caller-owned transactions and safe evidence."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import re

from sqlalchemy import JSON, not_, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from .contracts import AgentContext, CapabilityResult, Observation
from .errors import (AmbiguousTarget, CapabilityError, CapabilityNotAllowed, CapabilityUnavailable,
                     ConfirmationRequired, DatasetChangedError, InvalidCapabilityRequest, InvalidCapabilityCursor,
                     OperationConflict, OperationNotFound)
from .receipts import _sanitize
from app.persistence.models import (ChangeLog, DatasetState, Department, OperationReceipt,
                                    StoreProfile, SyncJob, SyncJobDetail)
from app.stores.domain import InvalidStoreChanges, UNSET
from app.web import utc_datetime


def boundary(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except CapabilityError:
            raise
        except InvalidStoreChanges:
            raise InvalidCapabilityRequest() from None
        except RuntimeError as exc:
            if str(exc) == "DATASET_CHANGED":
                raise DatasetChangedError() from None
            if str(exc) == "INVALID_CURSOR":
                raise InvalidCapabilityCursor() from None
            raise CapabilityUnavailable() from None
        except SQLAlchemyError:
            raise CapabilityUnavailable() from None
        except (ValueError, TypeError, AttributeError):
            raise InvalidCapabilityRequest() from None
    return call


class OrganizationCapabilities:
    def __init__(self, sessions, reads, stores, jobs, receipts, observations, *, environment="production"):
        if environment not in {"production", "test"}:
            raise ValueError("invalid agent environment")
        self.sessions, self.reads, self.stores = sessions, reads, stores
        self.jobs, self.receipts, self.observations = jobs, receipts, observations
        self.environment = environment

    def _authorize(self, context: AgentContext, *, write=False):
        if not isinstance(context, AgentContext) or context.environment != self.environment:
            raise CapabilityNotAllowed()
        if context.actor_type == "ci_agent":
            if context.environment != "test" or not context.run_id or not context.run_id.startswith(("test-", "test_")):
                raise CapabilityNotAllowed()
        if write and context.environment == "production" and context.approved is not True:
            raise ConfirmationRequired()
        from .errors import InitializationIncomplete
        with self.sessions() as db:
            self._bind_policy(db, context)
            state = db.get(DatasetState, 1)
            if state is None or state.initialization_status != 'complete':
                raise InitializationIncomplete()

    @staticmethod
    def _bind_policy(db, context):
        if context.actor_type != "ci_agent":
            return
        bind = db.get_bind()
        url = bind.engine.url
        # Isolated in-memory databases are supported only by direct unit construction.
        # Runtime uses create_mysql_engine and cannot construct SQLite.
        if url.drivername == "sqlite" and url.database in (None, "", ":memory:"):
            return
        if url.drivername != "mysql+pymysql" or not (url.database or "").endswith("_test"):
            raise CapabilityNotAllowed()
        actual = db.scalar(text("SELECT DATABASE()"))
        if actual != url.database or not actual.endswith("_test"):
            raise CapabilityNotAllowed()

    @staticmethod
    def _page_filters(filters):
        limit = filters.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise InvalidCapabilityRequest()

    def _read_result(self, db, data, meta, *, target_quality=None):
        obs = self.observations._base(db, "submitted", {"read": True})
        qualities = []
        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"sync_quality", "primary_store_status"}: qualities.append(child)
                    elif isinstance(child, (dict, list)): collect(child)
            elif isinstance(value, list):
                for child in value: collect(child)
        collect(data)
        if target_quality: qualities.append(target_quality)
        if "inconsistent" in qualities:
            obs = replace(obs, fact_quality="inconsistent", next_action="inspect_target")
        elif any(value in {"unknown", "pending_verification", "pending"} for value in qualities) or data is None:
            obs = replace(obs, fact_quality="unknown", next_action="refresh_target")
        elif any(value in {"partial", "incomplete"} for value in qualities):
            obs = replace(obs, fact_quality="partial", next_action="inspect_target")
        if data is None:
            obs = replace(obs, execution="unconfirmed", next_action="refresh_target")
        return CapabilityResult(None, {"data": data, "meta": meta}, obs, {}, write_operation=False)

    def _read(self, context, name, *args, **filters):
        self._authorize(context)
        self._page_filters(filters)
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            state = db.get(DatasetState, 1)
            if state is None or state.initialization_status != "complete":
                meta = self.reads._meta(state) if state else {"dataset_epoch":None, "data_version":None, "next_cursor":None}
                return self._read_result(db, None, meta)
            if name in {"get_store", "list_store_employees"}:
                self.reads._check_version(state, filters)
                department = db.get(Department, args[0])
                profile = db.get(StoreProfile, args[0]) if department else None
                target_status = ("missing" if department is None else "not_store" if not profile or not profile.is_store
                                 else "inactive" if department.status != "active" or department.is_virtual_root else None)
                if target_status:
                    result = self._read_result(db, None, self.reads._meta(state))
                    return replace(result, observation=replace(result.observation, evidence={**result.observation.evidence, "target_status":target_status}))
            data, meta = getattr(self.reads, name + "_in_session")(db, *args, **filters)
            quality = None
            if name in {"get_store", "list_store_employees"}:
                department = db.get(Department, args[0])
                quality = department.sync_quality if department else None
            elif name == "list_stores":
                values = [db.get(Department, row["id"]).sync_quality for row in data]
                quality = next((q for q in ("inconsistent", "unknown", "pending_verification", "partial") if q in values), None)
            return self._read_result(db, data, meta, target_quality=quality)

    @boundary
    def status(self, context): return self._read(context, "status")
    @boundary
    def get_department(self, context, department_id): return self._read(context, "get_department", department_id)
    @boundary
    def list_employees(self, context, **filters): return self._read(context, "list_employees", **filters)
    @boundary
    def get_employee(self, context, employee_id): return self._read(context, "get_employee", employee_id)
    @boundary
    def list_stores(self, context, **filters): return self._read(context, "list_stores", **filters)
    @boundary
    def get_store(self, context, store_id): return self._read(context, "get_store", store_id)
    @boundary
    def list_store_employees(self, context, store_id, **filters): return self._read(context, "list_store_employees", store_id, **filters)

    @boundary
    def find_departments(self, context, *, department_id=None, name=None, path=None, **filters):
        self._authorize(context)
        self._page_filters(filters)
        if sum(value is not None for value in (department_id, name, path)) > 1:
            raise InvalidCapabilityRequest()
        if not any(value is not None for value in (department_id, name, path)):
            return self._read(context, "list_departments", **filters)
        if "cursor" in filters:
            raise InvalidCapabilityRequest()
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            state = db.get(DatasetState, 1)
            if state is None or state.initialization_status != "complete":
                meta = self.reads._meta(state) if state else {"dataset_epoch":None, "data_version":None, "next_cursor":None}
                return self._read_result(db, None, meta)
            self.reads._check_version(state, filters)
            candidates, page_filters = [], {**filters, "limit":500}
            while True:
                rows, meta = self.reads.list_departments_in_session(db, **page_filters)
                for row in rows:
                    if ((department_id is not None and row["id"] == department_id)
                        or (name is not None and row["name"] == name)
                        or (path is not None and row["path"] == (path.split("/") if isinstance(path, str) else list(path)))):
                        candidates.append(row)
                if not meta["next_cursor"]: break
                page_filters["cursor"] = meta["next_cursor"]
            if len(candidates) > 1:
                raise AmbiguousTarget([{key: row[key] for key in ("id", "name", "path", "status")} for row in candidates])
            return self._read_result(db, candidates, self.reads._meta(state))

    @boundary
    def preview_store_changes(self, context, changes, expected_version):
        self._authorize(context)
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            data = self.stores.preview_in_session(db, changes, expected_version)
            return self._read_result(db, data, self.reads._meta(db.get(DatasetState, 1)))

    @staticmethod
    def _hash(capability, params):
        return hashlib.sha256(json.dumps({"capability":capability, "params":params}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _changes(changes):
        def tagged(value, normalize=False):
            if value is UNSET: return {"present":False}
            if normalize and value is not None: value = value.strip() or None
            return {"present":True, "value":value}
        for c in changes:
            if not isinstance(c.department_id, str) or not c.department_id or type(c.is_store) is not bool:
                raise InvalidCapabilityRequest()
            for value in (c.store_code, c.notes):
                if value is not UNSET and value is not None and not isinstance(value, str):
                    raise InvalidCapabilityRequest()
        return sorted([{"department_id":c.department_id, "is_store":c.is_store,
                        "store_code":tagged(c.store_code, True), "notes":tagged(c.notes)} for c in changes], key=lambda c:c["department_id"])

    def _write(self, context, capability, key, params, action):
        self._authorize(context, write=True)
        if not isinstance(key, str) or not key.strip() or len(key) > 191:
            raise InvalidCapabilityRequest()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            row = self.receipts.create(db, context, capability, key, self._hash(capability, params), now)
            if row.status == "recorded":
                action(db, row, now)
            return self._receipt_result(db, row)

    @boundary
    def apply_store_changes(self, context, changes, expected_version, idempotency_key, approval_token=None, *, expected_epoch=None):
        self._authorize(context, write=True)
        if not expected_epoch or type(expected_version) is not int or expected_version < 0:
            raise InvalidCapabilityRequest()
        params = {"changes":self._changes(changes), "expected_epoch":expected_epoch, "expected_version":expected_version}
        def apply(db, row, now):
            state = self.receipts._lock_state(db)
            if state.dataset_epoch != expected_epoch or state.data_version != expected_version:
                raise DatasetChangedError()
            result = self.stores.apply_in_session(db, changes, expected_version, context.actor_id, now)
            self.receipts.mark_submitted(db, row.operation_id, result.dataset_epoch, result.data_version,
                                         {"changed_count":result.changed_count}, list(result.audit_ids), now)
        return self._write(context, "apply_store_changes", idempotency_key, params, apply)

    @staticmethod
    def _sync_scope(db, job_type, root):
        if job_type not in {"initialize", "full", "reconcile", "subtree"}:
            raise InvalidCapabilityRequest()
        if job_type == "subtree":
            department = db.scalar(select(Department).where(Department.id == root).with_for_update().execution_options(populate_existing=True)) if root else None
            if department is None or department.status != "active" or department.is_virtual_root:
                raise InvalidCapabilityRequest()
        elif root is not None:
            raise InvalidCapabilityRequest()

    @boundary
    def request_sync(self, context, job_type, idempotency_key, approval_token=None, *, root_department_id=None):
        def submit(db, row, now):
            self._sync_scope(db, job_type, root_department_id)
            job, reused = self.jobs.submit_in_session(db, job_type, root_department_id, context.actor_id, now, trigger_source=context.actor_type)
            db.flush()
            state = self.receipts._lock_state(db)
            self.receipts.mark_accepted(db, row.operation_id, job.id, state.dataset_epoch, state.data_version, {"job_id":job.id, "reused":reused}, now)
        return self._write(context, "request_sync", idempotency_key, {"job_type":job_type, "root_department_id":root_department_id}, submit)

    @boundary
    def retry_sync_job(self, context, job_id, idempotency_key, approval_token=None):
        def retry(db, row, now):
            job = db.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update().execution_options(populate_existing=True))
            if job is None: raise OperationNotFound()
            self._sync_scope(db, job.type, job.root_department_id)
            if job.status != "failed": raise OperationConflict()
            job = self.jobs.retry_in_session(db, job_id, context.actor_id, now)
            db.flush()
            state = self.receipts._lock_state(db)
            self.receipts.mark_accepted(db, row.operation_id, job.id, state.dataset_epoch, state.data_version, {"job_id":job.id}, now)
        return self._write(context, "retry_sync_job", idempotency_key, {"job_id":job_id}, retry)

    @staticmethod
    def _error(code):
        return code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code) else None

    def _receipt_result(self, db, row, *, write_operation=True):
        current = self.observations._state(db)
        epoch = row.committed_epoch if row.committed_epoch is not None else row.before_epoch
        version = row.committed_version if row.committed_version is not None else row.before_version
        status = {"recorded":"request_recorded", "accepted":"accepted", "submitted":"submitted", "failed":"failed"}.get(row.status, "unconfirmed")
        summary = _sanitize({k:v for k,v in (row.result_summary or {}).items() if k != "audit_ids"})
        if row.status in {"submitted", "failed"}:
            evidence = {"status": status}
            if row.job_id:
                evidence["job_id"] = row.job_id
            failed = summary.get("failed_detail_count")
            if type(failed) is int and failed >= 0:
                evidence["failed_detail_count"] = failed
                if failed and status == "submitted":
                    status = "partial"
            # 终态只用已冻结的任务证据；旧回执缺失的计数不从后续重试猜补。
            obs = self.observations._base(db, status, evidence, fact_quality="partial" if status == "partial" else None)
        elif row.status == "accepted" and row.job_id:
            obs = self.observations.observation_for_job(db, row.job_id)
        else:
            obs = self.observations.observation_for_status(db, status, row.job_id) if status != "request_recorded" else self.observations._base(db, status)
        if status == "unconfirmed": obs = replace(obs, execution="unconfirmed", fact_quality="unknown", next_action="inspect_status")
        if current is None or current.dataset_epoch != epoch:
            obs = replace(obs, execution="unconfirmed", fact_quality="inconsistent", next_action="refresh_dataset")
        obs = replace(obs, dataset_epoch=epoch, data_version=version, evidence={**obs.evidence, "current_dataset_epoch":current.dataset_epoch if current else None, "current_data_version":current.data_version if current else None})
        audits = list((row.result_summary or {}).get("audit_ids", []))
        if row.status == "accepted" and row.job_id:
            audits = list(db.scalars(select(ChangeLog.id).where(ChangeLog.job_id == row.job_id).order_by(ChangeLog.id)))
        data = {**summary, "summary":summary, "status":row.status if row.status in {"recorded", "accepted", "submitted", "failed"} else "unknown", "capability":row.capability if row.capability in {"apply_store_changes", "request_sync", "retry_sync_job"} else "unknown", "job_id":row.job_id, "committed_epoch":row.committed_epoch,
                "committed_version":row.committed_version, "error_code":self._error(row.error_code)}
        return CapabilityResult(row.operation_id, data, obs, {"actor_id":row.actor_id, "environment":row.environment, "audit_ids":audits}, write_operation=write_operation)

    @boundary
    def get_operation(self, context, *, operation_id=None, idempotency_key=None):
        self._authorize(context)
        if (operation_id is None) == (idempotency_key is None): raise InvalidCapabilityRequest()
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            self.observations._state(db)  # Establish the same RR snapshot as the receipt.
            stmt = select(OperationReceipt).where(OperationReceipt.actor_id == context.actor_id, OperationReceipt.environment == context.environment)
            stmt = stmt.where(OperationReceipt.operation_id == operation_id) if operation_id is not None else stmt.where(OperationReceipt.idempotency_key == idempotency_key)
            row = db.scalar(stmt)
            if row is None: raise OperationNotFound()
            return self._receipt_result(db, row, write_operation=False)

    @boundary
    def get_sync_job(self, context, job_id):
        self._authorize(context)
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            self.observations._state(db)
            job = db.get(SyncJob, job_id)
            if job is None: raise OperationNotFound()
            details = [{"id":d.id, "object_type":d.object_type, "object_id":d.object_id, "status":d.status, "error_code":self._error(d.error_code), "change_log_id":d.change_log_id} for d in db.scalars(select(SyncJobDetail).where(SyncJobDetail.job_id == job_id).order_by(SyncJobDetail.id))]
            operations = list(db.scalars(select(OperationReceipt.operation_id).where(OperationReceipt.job_id == job_id, OperationReceipt.actor_id == context.actor_id, OperationReceipt.environment == context.environment).order_by(OperationReceipt.operation_id)))
            data = {"job_id":job.id, "type":job.type, "root_department_id":job.root_department_id, "status":job.status, "attempt":job.attempt, "success_count":job.success_count, "failure_count":job.failure_count, "error_code":self._error(job.error_code), "details":details, "operation_ids":operations}
            return CapabilityResult(None, data, self.observations.observation_for_job(db, job_id), {}, write_operation=False)

    @boundary
    def get_change_logs(self, context, **filters):
        self._authorize(context)
        self._page_filters(filters)
        filter_keys = ("object_type", "object_id", "source", "job_id", "actor", "action", "committed_after", "committed_before")
        if set(filters) - set(filter_keys) - {"limit", "cursor", "dataset_epoch", "data_version"}:
            raise InvalidCapabilityRequest()
        normalized = {key:filters.get(key) for key in filter_keys}
        normalized["limit"] = filters.get("limit", 100)
        action = normalized["action"]
        if action not in (None, "create", "update", "delete"):
            raise InvalidCapabilityRequest()
        for key in ("committed_after", "committed_before"):
            value = normalized[key]
            if value is not None:
                if not isinstance(value, datetime) or value.utcoffset() is None:
                    raise InvalidCapabilityRequest()
                normalized[key] = value.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        cursor = filters.get("cursor")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise InvalidCapabilityCursor()
        cursor_filters = {**normalized, "cursor":cursor}
        with self.sessions() as db, db.begin():
            self._bind_policy(db, context)
            state = db.get(DatasetState, 1)
            if state is None:
                return self._read_result(db, None, {"dataset_epoch":None, "data_version":None, "next_cursor":None})
            self.reads._check_version(state, filters)
            last_id = self.reads._last_id(state, "change_logs", cursor_filters)
            stmt = select(ChangeLog).where(ChangeLog.object_type.in_(("store", "department", "employee", "sync_job"))).order_by(ChangeLog.id.desc())
            for key in ("object_type", "object_id", "source", "job_id", "actor"):
                if normalized[key] is not None: stmt = stmt.where(getattr(ChangeLog, key) == normalized[key])
            before_null = or_(ChangeLog.before_data.is_(None), ChangeLog.before_data == JSON.NULL)
            after_null = or_(ChangeLog.after_data.is_(None), ChangeLog.after_data == JSON.NULL)
            if action == "create": stmt = stmt.where(before_null)
            if action == "delete": stmt = stmt.where(after_null, not_(before_null))
            if action == "update": stmt = stmt.where(not_(before_null), not_(after_null))
            for key, column, lower in (("committed_after", ChangeLog.committed_at, True), ("committed_before", ChangeLog.committed_at, False)):
                if normalized[key] is not None:
                    value = datetime.fromisoformat(normalized[key])
                    stmt = stmt.where(column >= value if lower else column <= value)
            if last_id is not None:
                try:
                    identifier = int(last_id)
                except (TypeError, ValueError):
                    raise InvalidCapabilityCursor() from None
                stmt = stmt.where(ChangeLog.id < identifier)
            limit = normalized["limit"]
            rows = list(db.scalars(stmt.limit(limit + 1)))
            page = rows[:limit]
            data = [{"id":r.id, "object_type":r.object_type, "object_id":r.object_id, "source":r.source, "actor":r.actor, "job_id":r.job_id,
                     "action":"create" if r.before_data is None else "delete" if r.after_data is None else "update",
                     "before":_sanitize(r.before_data), "after":_sanitize(r.after_data), "committed_at":utc_datetime(r.committed_at)} for r in page]
            next_id = str(page[-1].id) if len(rows) > limit else None
            cursor = self.reads._next_cursor(state, "change_logs", cursor_filters, next_id)
            return self._read_result(db, data, self.reads._meta(state, cursor))
