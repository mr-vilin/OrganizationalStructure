"""独立内部 HTTP 适配；不导入业务实现，不重试或推断执行结果。"""
import base64
import math
import re
from typing import Any, Literal
from urllib.parse import unquote

import httpx
from pydantic import SecretStr

from .auth import AuthenticationError, validate_principal
from .models import AgentPrincipal, ToolError, ToolResult
from .trace import redact_trace


_PREFIX = "/internal/capabilities"
# 上游错误只接受已知稳定码，消息始终由本地生成。
_ERRORS = {
    "AGENT_SERVICE_UNAUTHORIZED": "The capability service rejected its service identity.",
    "CAPABILITY_NOT_ALLOWED": "This capability is not allowed.",
    "CONFIRMATION_REQUIRED": "Trusted human confirmation is required.",
    "OPERATION_NOT_FOUND": "The operation was not found in this identity scope.",
    "DEPARTMENT_NOT_FOUND": "The department was not found.",
    "EMPLOYEE_NOT_FOUND": "The employee was not found.",
    "STORE_NOT_FOUND": "The store was not found.",
    "JOB_NOT_FOUND": "The sync job was not found.",
    "NOT_FOUND": "The capability route was not found.",
    "METHOD_NOT_ALLOWED": "The capability method is not allowed.",
    "DATASET_CHANGED": "The dataset changed; refresh its epoch and version before another write.",
    "OPERATION_CONFLICT": "The operation conflicts with the original request; observe it with get_operation.",
    "AMBIGUOUS_TARGET": "The target is ambiguous; select a safe candidate explicitly.",
    "JOB_NOT_RETRYABLE": "The sync job cannot currently be retried.",
    "INVALID_CURSOR": "The cursor is invalid or does not match the filters.",
    "INVALID_CAPABILITY_REQUEST": "The capability parameters are invalid.",
    "INVALID_JOB_SCOPE": "The sync job scope is invalid.",
    "VALIDATION_ERROR": "The capability parameters are invalid.",
    "INITIALIZATION_INCOMPLETE": "An initialized committed dataset is not yet available.",
    "DATABASE_NOT_CONFIGURED": "The capability database is not configured.",
    "DATABASE_UNAVAILABLE": "The capability database is unavailable.",
    "DATABASE_ERROR": "The capability database could not complete the request.",
    "CAPABILITY_UNAVAILABLE": "The capability is temporarily unavailable.",
    "CAPABILITY_ERROR": "The capability request could not be completed.",
}
_FIELDS = frozenset({
    "changes", "department_id", "employee_id", "store_id", "job_id", "operation_id", "name", "path",
    "parent_id", "root_id", "include_descendants", "include_inactive", "primary_store_id", "membership",
    "object_type", "object_id", "source", "actor", "action", "committed_after", "committed_before",
    "limit", "cursor", "dataset_epoch", "data_version", "is_store", "store_code", "notes",
    "expected_epoch", "expected_version", "idempotency_key", "job_type", "root_department_id",
})


def _safe_fields(error: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    raw = error.get("fields")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        location = item.get("loc")
        if isinstance(location, list) and location and location[0] in ("body", "query", "path"):
            location = location[1:]
        elif isinstance(item.get("field"), str):
            location = item["field"].split(".")
        else:
            continue
        if location and all(
            type(part) is int and 0 <= part <= 10000
            or isinstance(part, str) and (part in _FIELDS or re.fullmatch(r"[0-9]{1,5}", part))
            for part in location
        ):
            fields.append({"field": ".".join(str(part) for part in location)})
    if error.get("code") == "AMBIGUOUS_TARGET" and isinstance(error.get("candidates"), list):
        candidates = []
        for candidate in error["candidates"]:
            if not isinstance(candidate, dict):
                continue
            safe = {key: value for key in ("id", "name", "path", "status")
                    if isinstance((value := candidate.get(key)), str)
                    or key == "path" and isinstance(value, list) and all(isinstance(part, str) for part in value)}
            if "id" in safe:
                candidates.append(redact_trace(safe))
        fields.append({"candidates": candidates})
    return fields


class CapabilityHttpClient:
    """固定服务地址与令牌；注入 client 时一并转移其关闭责任。

    base_url 只接受 HTTP(S) origin 或该 origin 的 /internal/capabilities。
    path 为可信工具路由构造的相对能力路径，不能包含 URL、查询或目录跳转。
    async with 或 aclose() 关闭所有权内的 client；client/transport 不可同时提供。
    """

    def __init__(
        self, base_url: str, service_token: SecretStr, *, environment: Literal["production", "test"],
        transport: httpx.AsyncBaseTransport | None = None, client: httpx.AsyncClient | None = None,
        connect_timeout: float = 5.0, read_timeout: float = 30.0,
    ):
        try:
            base = httpx.URL(base_url)
            secret = service_token.get_secret_value() if isinstance(service_token, SecretStr) else ""
            valid = (
                base.scheme in ("http", "https") and bool(base.host) and not base.userinfo
                and not base.query and not base.fragment and base.path.rstrip("/") in ("", _PREFIX)
                and environment in ("production", "test") and bool(secret)
                and all(33 <= ord(char) <= 126 for char in secret)
                and all(type(value) in (int, float) and math.isfinite(value) and value > 0
                        for value in (connect_timeout, read_timeout))
                and not (client is not None and transport is not None)
            )
        except (ValueError, TypeError, httpx.InvalidURL):
            valid = False
        if not valid:
            raise ValueError("Invalid capability HTTP client configuration.") from None
        self._base = base.copy_with(path=_PREFIX, query=None, fragment=None)
        self._token = service_token
        self._environment = environment
        self._timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout)
        self._client = client if client is not None else httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False)

    async def __aenter__(self) -> "CapabilityHttpClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """显式关闭底层 client（包括注入的 client），可重复调用。"""
        await self._client.aclose()

    async def call(
        self, path: str, payload: dict | None, principal: AgentPrincipal, *, approved: bool = False,
    ) -> ToolResult:
        return await self._request("POST", path, principal, payload=payload, approved=approved)

    async def read(self, path: str, params: dict, principal: AgentPrincipal) -> ToolResult:
        return await self._request("GET", path, principal, params=params)

    async def _request(self, method, path, principal, *, payload=None, params=None, approved=False) -> ToolResult:
        try:
            principal = validate_principal(principal, environment=self._environment)
        except AuthenticationError:
            return ToolResult.failure("MCP_SERVICE_UNAUTHORIZED")
        # 拒绝编码目录跳转及二次编码；ID 里的普通百分号转义仍可使用。
        decoded = unquote(path) if isinstance(path, str) else ""
        if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
                or any(char in decoded for char in ("\\", "?", "#", "%"))
                or any(part in (".", "..") for part in decoded.split("/"))
                or decoded.startswith("//") or any(ord(char) < 32 for char in decoded)):
            return ToolResult.failure("CAPABILITY_FORBIDDEN")
        if self._client.is_closed:
            return ToolResult.failure("UPSTREAM_UNAVAILABLE")
        headers = {
            "Authorization": "Bearer " + self._token.get_secret_value(),
            "X-Agent-Actor-Type": principal.actor_type,
            "X-Agent-Environment": principal.environment,
            "X-Agent-Approved": "true" if approved is True else "false",
            "X-Agent-Identity-Encoding": "base64url-utf8",
        }
        for name, value in (("Actor-Id", principal.actor_id), ("Run-Id", principal.run_id), ("Case-Id", principal.case_id)):
            if value is not None:
                headers["X-Agent-" + name] = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
        # 不调用 build_request，避免合并注入 client 的默认 params/headers/cookies。
        request = httpx.Request(method, self._base.copy_with(path=_PREFIX + path), params=params, json=payload,
                                headers=headers, extensions={"timeout": self._timeout.as_dict()})
        try:
            response = await self._client.send(request, auth=None, follow_redirects=False)
        except httpx.TimeoutException:
            result = ToolResult.failure("UPSTREAM_TIMEOUT")
            if method == "POST":
                result.observation = {"execution_status": "unconfirmed"}
            return result
        except httpx.RequestError:
            return ToolResult.failure("UPSTREAM_UNAVAILABLE")
        if response.is_redirect:
            return ToolResult.failure("UPSTREAM_INVALID_RESPONSE")
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            return ToolResult.failure("UPSTREAM_INVALID_RESPONSE")
        if not isinstance(body, dict):
            return ToolResult.failure("UPSTREAM_INVALID_RESPONSE")
        if response.is_success:
            required = {"operation_id", "data", "observation", "audit"}
            if (not required.issubset(body) or body.get("error") is not None
                    or body["operation_id"] is not None and not isinstance(body["operation_id"], str)
                    or not isinstance(body["observation"], dict) or not isinstance(body["audit"], dict)):
                return ToolResult.failure("UPSTREAM_INVALID_RESPONSE")
            return ToolResult(**redact_trace({key: body[key] for key in required}))
        error = body.get("error")
        if not isinstance(error, dict):
            return ToolResult.failure("UPSTREAM_INVALID_RESPONSE")
        code = error.get("code")
        if not isinstance(code, str) or code not in _ERRORS:
            return ToolResult.failure("UPSTREAM_UNAVAILABLE" if response.is_server_error else "UPSTREAM_INVALID_RESPONSE")
        return ToolResult(operation_id=None, data=None, observation={}, audit={}, error=ToolError(
            code=code, message=_ERRORS[code], retryable=error.get("retryable") is True,
            confirmation_required=code == "CONFIRMATION_REQUIRED", fields=_safe_fields(error),
        ))
