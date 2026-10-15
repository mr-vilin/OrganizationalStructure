"""组织能力层的稳定公开入口。"""
from .contracts import AgentContext, CapabilityResult, Observation
from .errors import (
    AmbiguousTarget, CapabilityError, CapabilityNotAllowed, CapabilityUnavailable,
    ConfirmationRequired, DatasetChangedError, InvalidCapabilityCursor,
    InvalidCapabilityRequest, OperationConflict, OperationNotFound,
)
from .service import OrganizationCapabilities

__all__ = [
    "AgentContext", "CapabilityResult", "Observation", "OrganizationCapabilities",
    "AmbiguousTarget", "CapabilityError", "CapabilityNotAllowed", "CapabilityUnavailable",
    "ConfirmationRequired", "DatasetChangedError", "InvalidCapabilityCursor",
    "InvalidCapabilityRequest", "OperationConflict", "OperationNotFound",
]
