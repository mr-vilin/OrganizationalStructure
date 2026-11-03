"""Stable errors exposed by the capability boundary."""
class CapabilityError(Exception):
    code = "CAPABILITY_ERROR"
    status = 500
    message = "Capability request failed"

    def __init__(self, message: str | None = None):
        self.detail = self.message
        super().__init__(self.detail)

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.detail}}

class ConfirmationRequired(CapabilityError):
    code, status, message = "CONFIRMATION_REQUIRED", 409, "Explicit confirmation is required"

class OperationNotFound(CapabilityError):
    code, status, message = "OPERATION_NOT_FOUND", 404, "Operation was not found"

class CapabilityNotAllowed(CapabilityError):
    code, status, message = "CAPABILITY_NOT_ALLOWED", 403, "Capability is not allowed"

class OperationConflict(CapabilityError):
    code, status, message = "OPERATION_CONFLICT", 409, "Operation conflicts with current state"

class InvalidCapabilityRequest(CapabilityError):
    code, status, message = "INVALID_CAPABILITY_REQUEST", 422, "Invalid capability parameters"

class DatasetChangedError(CapabilityError):
    code, status, message = "DATASET_CHANGED", 409, "Dataset changed; refresh before retrying"

class AmbiguousTarget(CapabilityError):
    code, status, message = "AMBIGUOUS_TARGET", 409, "Target is ambiguous"

    def __init__(self, candidates):
        super().__init__()
        self.candidates = candidates

    def to_dict(self):
        return {"error": {"code": self.code, "message": self.detail, "candidates": self.candidates}}

class CapabilityUnavailable(CapabilityError):
    code, status, message = "CAPABILITY_UNAVAILABLE", 503, "Capability is temporarily unavailable"

class InitializationIncomplete(CapabilityError):
    code, status, message = 'INITIALIZATION_INCOMPLETE', 409, '请由管理员完成初始化向导'

class InvalidCapabilityCursor(CapabilityError):
    code, status, message = "INVALID_CURSOR", 400, "Cursor is invalid or does not match filters"
