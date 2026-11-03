"""仅追踪允许的元数据，递归脱敏，不记录业务原文或异常。"""
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
import re
import unicodedata
from typing import Any

from .auth import validate_principal
from .models import AgentPrincipal
from .policy import TOOL_LEVELS

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = ("secret", "token", "password", "csrf", "authorization", "oauth")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_CREDENTIAL_TEXT = re.compile(r"(?:\bBearer\s+|[a-z][a-z0-9+.-]*://[^\s/]*@)", re.IGNORECASE)


def redact_trace(value: Any) -> Any:
    """返回 JSON 安全副本；未知对象、循环和敏感键值不调用 repr。"""
    return _redact(value, set())


def _redact(value: Any, active: set[int]) -> Any:
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, str):
        return _REDACTED if _CREDENTIAL_TEXT.search(value) else value
    if not isinstance(value, (Mapping, list, tuple)) or id(value) in active:
        return _REDACTED
    active.add(id(value))
    try:
        if isinstance(value, Mapping):
            return {key: _REDACTED if any(part in key.casefold() for part in _SENSITIVE_KEYS)
                    else _redact(item, active) for key, item in value.items() if isinstance(key, str)}
        return [_redact(item, active) for item in value]
    finally:
        active.remove(id(value))


def _identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 191 or any(
        char.isspace() or unicodedata.category(char).startswith("C") for char in value
    ):
        return _REDACTED
    return value


class Tracer:
    """有界的安全元数据记录器；records 和 record 均返回独立副本。"""

    def __init__(self, *, max_records: int = 1000):
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records must be a positive integer.")
        self._records: deque[dict[str, Any]] = deque(maxlen=max_records)

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(record) for record in self._records)

    def record(
        self, *, tool_name: str, principal: AgentPrincipal,
        operation_id: str | None = None, code: str | None = None, **_discarded: Any,
    ) -> dict[str, Any]:
        """写入允许字段；额外参数被丢弃，禁止存入原始参数/响应/异常。"""
        principal = validate_principal(principal, environment=getattr(principal, "environment", None))
        record = redact_trace({
            "tool_name": tool_name if tool_name in TOOL_LEVELS else _REDACTED,
            "actor_type": principal.actor_type,
            "actor_id": _identifier(principal.actor_id),
            "environment": principal.environment,
            "run_id": _identifier(principal.run_id),
            "case_id": _identifier(principal.case_id),
            "operation_id": _identifier(operation_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "code": code if code is None or isinstance(code, str) and _CODE.fullmatch(code) else _REDACTED,
        })
        self._records.append(record)
        return dict(record)
