"""Protected transport adapter for trusted internal capability clients."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StrictBool, StrictInt

from ..dependencies import get_agent_capabilities, get_agent_context
from ..stores.domain import StorePatch, UNSET
from .contracts import AgentContext
from .service import OrganizationCapabilities

router = APIRouter(prefix="/internal/capabilities", tags=["internal-capabilities"])
Context = Annotated[AgentContext, Depends(get_agent_context)]
Capabilities = Annotated[OrganizationCapabilities, Depends(get_agent_capabilities)]


class StoreChange(BaseModel):
    department_id: str = Field(min_length=1)
    is_store: StrictBool
    store_code: str | None = None
    notes: str | None = None

    def to_patch(self) -> StorePatch:
        return StorePatch(self.department_id, self.is_store,
                          self.store_code if "store_code" in self.model_fields_set else UNSET,
                          self.notes if "notes" in self.model_fields_set else UNSET)


class StorePreviewRequest(BaseModel):
    changes: list[StoreChange]
    expected_version: Annotated[StrictInt, Field(ge=0)]


class StoreApplyRequest(StorePreviewRequest):
    expected_epoch: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=191)


class PageQuery(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None
    dataset_epoch: str | None = None
    data_version: int | None = Field(default=None, ge=0)
    include_inactive: bool = False


class DepartmentQuery(PageQuery):
    department_id: str | None = None
    name: str | None = None
    path: str | None = None
    parent_id: str | None = None
    root_id: str | None = None
    include_descendants: bool = False


class EmployeeQuery(PageQuery):
    department_id: str | None = None
    include_descendants: bool = False
    store_id: str | None = None
    primary_store_id: str | None = None


class StoreEmployeeQuery(PageQuery):
    membership: str = Field(default="all", pattern="^(all|primary)$")


class ChangeLogQuery(BaseModel):
    object_type: str | None = None
    object_id: str | None = None
    source: str | None = None
    job_id: str | None = None
    actor: str | None = None
    action: Literal["create", "update", "delete"] | None = None
    committed_after: datetime | None = None
    committed_before: datetime | None = None
    limit: int = Field(default=100, ge=1, le=500)
    cursor: str | None = None
    dataset_epoch: str | None = None
    data_version: int | None = Field(default=None, ge=0)


class IdempotentRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=191)


class SyncRequest(IdempotentRequest):
    job_type: Literal["initialize", "full", "reconcile", "subtree"]
    root_department_id: str | None = None


@router.get("/status")
def status(context: Context, capabilities: Capabilities):
    return capabilities.status(context).to_dict()


@router.post("/stores/batch/preview")
def preview_store_changes(body: StorePreviewRequest, context: Context, capabilities: Capabilities):
    return capabilities.preview_store_changes(context, [item.to_patch() for item in body.changes], body.expected_version).to_dict()


@router.post("/stores/batch/apply")
def apply_store_changes(body: StoreApplyRequest, context: Context, capabilities: Capabilities):
    return capabilities.apply_store_changes(
        context, [item.to_patch() for item in body.changes], body.expected_version,
        body.idempotency_key, expected_epoch=body.expected_epoch,
    ).to_dict()


@router.get("/departments")
def find_departments(query: Annotated[DepartmentQuery, Query()], context: Context, capabilities: Capabilities):
    return capabilities.find_departments(context, **query.model_dump(exclude_none=True)).to_dict()


@router.get("/departments/{department_id}")
def get_department(department_id: str, context: Context, capabilities: Capabilities):
    return capabilities.get_department(context, department_id).to_dict()


@router.get("/employees")
def list_employees(query: Annotated[EmployeeQuery, Query()], context: Context, capabilities: Capabilities):
    return capabilities.list_employees(context, **query.model_dump(exclude_none=True)).to_dict()


@router.get("/employees/{employee_id}")
def get_employee(employee_id: str, context: Context, capabilities: Capabilities):
    return capabilities.get_employee(context, employee_id).to_dict()


@router.get("/stores")
def list_stores(query: Annotated[PageQuery, Query()], context: Context, capabilities: Capabilities):
    return capabilities.list_stores(context, **query.model_dump(exclude_none=True)).to_dict()


@router.get("/stores/{store_id}")
def get_store(store_id: str, context: Context, capabilities: Capabilities):
    return capabilities.get_store(context, store_id).to_dict()


@router.get("/stores/{store_id}/employees")
def list_store_employees(store_id: str, query: Annotated[StoreEmployeeQuery, Query()], context: Context, capabilities: Capabilities):
    return capabilities.list_store_employees(context, store_id, **query.model_dump(exclude_none=True)).to_dict()


# Static lost-response lookup must precede the operation ID route.
@router.get("/operations/lookup")
def lookup_operation(
    idempotency_key: Annotated[str, Query(min_length=1, max_length=191)],
    context: Context, capabilities: Capabilities,
):
    return capabilities.get_operation(context, idempotency_key=idempotency_key).to_dict()


@router.get("/operations/{operation_id}")
def get_operation(operation_id: str, context: Context, capabilities: Capabilities):
    return capabilities.get_operation(context, operation_id=operation_id).to_dict()


@router.get("/change-logs")
def get_change_logs(query: Annotated[ChangeLogQuery, Query()], context: Context, capabilities: Capabilities):
    return capabilities.get_change_logs(context, **query.model_dump(exclude_none=True)).to_dict()


@router.get("/sync/jobs/{job_id}")
def get_sync_job(job_id: str, context: Context, capabilities: Capabilities):
    return capabilities.get_sync_job(context, job_id).to_dict()


@router.post("/sync/jobs", status_code=202)
def request_sync(body: SyncRequest, context: Context, capabilities: Capabilities):
    return capabilities.request_sync(context, body.job_type, body.idempotency_key, root_department_id=body.root_department_id).to_dict()


@router.post("/sync/jobs/{job_id}/retry", status_code=202)
def retry_sync_job(job_id: str, body: IdempotentRequest, context: Context, capabilities: Capabilities):
    return capabilities.retry_sync_job(context, job_id, body.idempotency_key).to_dict()
