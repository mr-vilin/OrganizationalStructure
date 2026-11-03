"""纯能力分级策略；不调用网络、不执行工具、不持有确认开关。"""
from enum import StrEnum
from types import MappingProxyType
from typing import NamedTuple

from .auth import AuthenticationError, validate_principal
from .models import AgentPrincipal


class CapabilityLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


# Task 4 的工具注册必须复用此唯一权威目录。
TOOL_LEVELS = MappingProxyType({
    "get_system_status": CapabilityLevel.L0,
    "find_departments": CapabilityLevel.L0,
    "get_department": CapabilityLevel.L0,
    "list_employees": CapabilityLevel.L0,
    "get_employee": CapabilityLevel.L0,
    "list_stores": CapabilityLevel.L0,
    "get_store": CapabilityLevel.L0,
    "list_store_employees": CapabilityLevel.L0,
    "get_change_logs": CapabilityLevel.L0,
    "get_sync_job": CapabilityLevel.L0,
    "get_operation": CapabilityLevel.L0,
    "preview_store_changes": CapabilityLevel.L1,
    "apply_store_changes": CapabilityLevel.L2,
    "request_sync": CapabilityLevel.L2,
    "retry_sync_job": CapabilityLevel.L2,
})


class PolicyDecision(NamedTuple):
    allowed: bool
    confirmation_required: bool
    code: str | None
    message: str | None


def decide(principal: AgentPrincipal, capability: str, approved: bool) -> PolicyDecision:
    """approved 只能由 Task 4 的可信隐藏确认依赖传入严格 bool。"""
    forbidden = PolicyDecision(False, False, "CAPABILITY_FORBIDDEN", "This capability is not allowed.")
    if not isinstance(principal, AgentPrincipal):
        return forbidden
    try:
        principal = validate_principal(principal, environment=getattr(principal, "environment", None))
    except AuthenticationError:
        return forbidden
    level = TOOL_LEVELS.get(capability) if isinstance(capability, str) else None
    if level not in (CapabilityLevel.L0, CapabilityLevel.L1, CapabilityLevel.L2):
        return forbidden
    if level == CapabilityLevel.L2 and principal.environment == "production" and approved is not True:
        return PolicyDecision(False, True, "CONFIRMATION_REQUIRED", "Trusted human confirmation is required.")
    return PolicyDecision(True, False, None, None)
