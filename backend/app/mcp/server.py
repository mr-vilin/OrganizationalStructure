"""官方 SDK 15 个工具；身份和确认来自可信配置与隐藏 Resolve 依赖。"""
import json
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote

from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver.exceptions import ToolError as SDKToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp.server.mcpserver.tools import Tool
from mcp.types import ToolAnnotations
from pydantic import StrictBool

from .auth import validate_principal
from .models import (AwareDatetime, Changes, Confirmation, Cursor, FindLimit,
                     Identifier, Key, Name, PageLimit, QueryText, ToolResult, Version)
from .policy import CapabilityLevel, TOOL_LEVELS
from .runtime import CapabilityServer, finish_confirmation_wait


def build_server(client, policy, tracer, *, principal=None, inbound_token=None,
                 environment=None, confirmation_timeout=60.0):
    """构造可嵌入的官方 SDK server；每个主体/CI case 使用独立实例。"""
    try:
        principal = validate_principal(principal, environment=environment)
        if not callable(getattr(policy, "decide", None)) or not callable(getattr(tracer, "record", None)):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("MCP_RUNTIME_NOT_CONFIGURED") from None
    tools = []
    public_fields = {}

    def register(fn):
        level = TOOL_LEVELS[fn.__name__]
        tool = Tool.from_function(fn, annotations=ToolAnnotations(read_only_hint=level == CapabilityLevel.L0,
                                  destructive_hint=level == CapabilityLevel.L2, open_world_hint=False))
        # Keep the SDK's normal validation/exception boundary, but never include
        # rejected values in its Pydantic error strings. Reject hidden/extra args.
        model = tool.fn_metadata.arg_model
        model.model_config.update(extra="forbid", hide_input_in_errors=True)
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema()
        tools.append(tool)
        public_fields[fn.__name__] = set(tool.parameters['properties'])
        return fn

    async def invoke(name, path, values, *, write=False, approved=False):
        finish_confirmation_wait()
        values = {k: v for k, v in values.items() if k in public_fields[name]}
        decision = policy.decide(principal, name, approved)
        if not decision.allowed:
            result = ToolResult.failure(decision.code)
        elif write:
            result = await client.call(path, values, principal, approved=approved)
        else:
            result = await client.read(path, {k: v.isoformat() if isinstance(v, datetime) else v
                                             for k, v in values.items() if v is not None}, principal)
        tracer.record(tool_name=name, principal=principal, operation_id=result.operation_id,
                      code=result.error.code if result.error else None)
        return result

    def ask(name, payload) -> Confirmation | Elicit[Confirmation]:
        decision = policy.decide(principal, name, False)
        if decision.allowed:
            return Confirmation(confirmed=True)
        if decision.confirmation_required:
            return Elicit("请确认执行 " + name + "：" + json.dumps(payload, ensure_ascii=False, sort_keys=True), Confirmation)
        return Confirmation(confirmed=False)

    def confirmed(value):
        return isinstance(value, AcceptedElicitation) and value.action == "accept" and value.data.confirmed is True

    def path_id(value):
        return quote(value, safe="")

    @register
    async def get_system_status() -> ToolResult:
        """读取组织数据、同步和观察状态。"""
        return await invoke("get_system_status", "/status", {})

    @register
    async def find_departments(department_id: Identifier | None = None, name: Name | None = None,
                               path: QueryText | None = None, parent_id: Identifier | None = None,
                               root_id: Identifier | None = None, include_descendants: StrictBool = False,
                               include_inactive: StrictBool = False, limit: FindLimit = 100,
                               cursor: Cursor | None = None, dataset_epoch: Key | None = None,
                               data_version: Version | None = None) -> ToolResult:
        """定位或分页查找部门；多个候选原样返回，不自动选择。"""
        values = locals()
        if sum(value is not None for value in (department_id, name, path)) > 1:
            raise SDKToolError("Only one department locator is allowed.")
        if cursor is not None and any(value is not None for value in (department_id, name, path)):
            raise SDKToolError("Exact department lookup cannot use cursor.")
        return await invoke("find_departments", "/departments", values)

    @register
    async def get_department(department_id: Identifier) -> ToolResult:
        """按稳定 ID 读取部门。"""
        return await invoke("get_department", "/departments/" + path_id(department_id), {})

    @register
    async def list_employees(department_id: Identifier | None = None, include_descendants: StrictBool = False,
                             store_id: Identifier | None = None, primary_store_id: Identifier | None = None,
                             include_inactive: StrictBool = False, limit: PageLimit = 100,
                             cursor: Cursor | None = None, dataset_epoch: Key | None = None,
                             data_version: Version | None = None) -> ToolResult:
        """按部门或门店筛选员工并分页读取。"""
        return await invoke("list_employees", "/employees", locals())

    @register
    async def get_employee(employee_id: Identifier) -> ToolResult:
        """按稳定 ID 读取员工。"""
        return await invoke("get_employee", "/employees/" + path_id(employee_id), {})

    @register
    async def list_stores(include_inactive: StrictBool = False, limit: PageLimit = 100,
                          cursor: Cursor | None = None, dataset_epoch: Key | None = None,
                          data_version: Version | None = None) -> ToolResult:
        """分页读取门店。"""
        return await invoke("list_stores", "/stores", locals())

    @register
    async def get_store(store_id: Identifier) -> ToolResult:
        """按稳定 ID 读取门店。"""
        return await invoke("get_store", "/stores/" + path_id(store_id), {})

    @register
    async def list_store_employees(store_id: Identifier, membership: Literal["all", "primary"] = "all",
                                   include_inactive: StrictBool = False, limit: PageLimit = 100,
                                   cursor: Cursor | None = None, dataset_epoch: Key | None = None,
                                   data_version: Version | None = None) -> ToolResult:
        """读取门店成员，支持全部或主门店关系。"""
        values = locals()
        values.pop("store_id")
        return await invoke("list_store_employees", "/stores/" + path_id(store_id) + "/employees", values)

    @register
    async def get_change_logs(object_type: QueryText | None = None, object_id: Identifier | None = None,
                              source: QueryText | None = None, job_id: Identifier | None = None,
                              actor: Key | None = None, action: Literal["create", "update", "delete"] | None = None,
                              committed_after: AwareDatetime | None = None, committed_before: AwareDatetime | None = None,
                              limit: PageLimit = 100, cursor: Cursor | None = None,
                              dataset_epoch: Key | None = None, data_version: Version | None = None) -> ToolResult:
        """分页读取安全审计；actor 只筛选业务日志，不改变调用身份。"""
        return await invoke("get_change_logs", "/change-logs", locals())

    @register
    async def get_sync_job(job_id: Identifier) -> ToolResult:
        """读取同步任务与观察证据；succeeded 不代表 verified。"""
        return await invoke("get_sync_job", "/sync/jobs/" + path_id(job_id), {})

    @register
    async def get_operation(operation_id: Identifier | None = None, idempotency_key: Key | None = None) -> ToolResult:
        """以 operation_id 或当前主体作用域的 idempotency_key 查询回执，恰选一种。"""
        if (operation_id is None) == (idempotency_key is None):
            raise SDKToolError("Provide exactly one of operation_id and idempotency_key.")
        if operation_id is not None:
            return await invoke("get_operation", "/operations/" + path_id(operation_id), {})
        return await invoke("get_operation", "/operations/lookup", {"idempotency_key": idempotency_key})

    @register
    async def preview_store_changes(changes: Changes, expected_version: Version) -> ToolResult:
        """预览最多 500 项门店变更，不提交修改。"""
        return await invoke("preview_store_changes", "/stores/batch/preview",
                            {"changes": [c.model_dump(exclude_unset=True) for c in changes], "expected_version": expected_version}, write=True)

    def confirm_apply(changes: Changes, expected_epoch: Key, expected_version: Version, idempotency_key: Key):
        return ask("apply_store_changes", {"changes": [c.model_dump(exclude_unset=True) for c in changes],
                                          "expected_epoch": expected_epoch, "expected_version": expected_version,
                                          "idempotency_key": idempotency_key})

    @register
    async def apply_store_changes(changes: Changes, expected_epoch: Key, expected_version: Version, idempotency_key: Key,
                                  confirmation: Annotated[ElicitationResult[Confirmation], Resolve(confirm_apply)]) -> ToolResult:
        """按世代、版本与幂等键提交门店变更；生产环境要求人工确认。"""
        return await invoke("apply_store_changes", "/stores/batch/apply",
                            {"changes": [c.model_dump(exclude_unset=True) for c in changes], "expected_epoch": expected_epoch,
                             "expected_version": expected_version, "idempotency_key": idempotency_key},
                            write=True, approved=confirmed(confirmation))

    def confirm_sync(job_type, root_department_id, idempotency_key):
        if (job_type == "subtree") != (root_department_id is not None):
            raise SDKToolError("Only subtree sync requires root_department_id.")
        return ask("request_sync", {"job_type": job_type, "root_department_id": root_department_id, "idempotency_key": idempotency_key})

    @register
    async def request_sync(job_type: Literal["initialize", "reconcile", "full", "subtree"], idempotency_key: Key,
                           confirmation: Annotated[ElicitationResult[Confirmation], Resolve(confirm_sync)],
                           root_department_id: Identifier | None = None) -> ToolResult:
        """申请同步任务；返回 accepted/任务 ID 后需观察任务。"""
        return await invoke("request_sync", "/sync/jobs", {"job_type": job_type, "root_department_id": root_department_id,
                            "idempotency_key": idempotency_key}, write=True, approved=confirmed(confirmation))

    def confirm_retry(job_id, idempotency_key):
        return ask("retry_sync_job", {"job_id": job_id, "idempotency_key": idempotency_key})

    @register
    async def retry_sync_job(job_id: Identifier, idempotency_key: Key,
                             confirmation: Annotated[ElicitationResult[Confirmation], Resolve(confirm_retry)]) -> ToolResult:
        """申请重试失败同步任务；不自动重复提交。"""
        return await invoke("retry_sync_job", "/sync/jobs/" + path_id(job_id) + "/retry",
                            {"idempotency_key": idempotency_key}, write=True, approved=confirmed(confirmation))

    assert {tool.name for tool in tools} == set(TOOL_LEVELS)
    return CapabilityServer(client=client, principal=principal, inbound_token=inbound_token, environment=environment,
                            confirmation_timeout=confirmation_timeout, tools=tools)
