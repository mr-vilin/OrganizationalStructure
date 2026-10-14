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
