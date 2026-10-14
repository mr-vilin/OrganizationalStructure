"""Immutable contracts shared by capability adapters and services."""
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Generic, Literal, TypeVar

ActorType = Literal["human_agent", "ci_agent"]
Environment = Literal["production", "test"]
Execution = Literal["request_recorded", "accepted", "running", "submitted", "verified", "partial", "failed", "unconfirmed"]
FactQuality = Literal["resolved", "partial", "unknown", "inconsistent", "not_applicable"]
T = TypeVar("T")

def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list): return tuple(_freeze(v) for v in value)
    if isinstance(value, set): return frozenset(_freeze(v) for v in value)
    if isinstance(value, tuple): return tuple(_freeze(v) for v in value)
    return value

def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)): return value
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)): return [_jsonable(v) for v in value]
    raise TypeError(f"value of type {type(value).__name__} is not JSON encodable")

@dataclass(frozen=True)
class AgentContext:
    actor_type: ActorType
    actor_id: str
    environment: Environment
    run_id: str | None = None
    case_id: str | None = None
    approved: bool = False

    def __post_init__(self) -> None:
        if self.actor_type not in ("human_agent", "ci_agent"):
            raise ValueError(f"unknown actor_type: {self.actor_type}")
        if self.environment not in ("production", "test"):
            raise ValueError(f"invalid environment: {self.environment}")
        if not self.actor_id:
            raise ValueError("actor_id is required")

@dataclass(frozen=True)
class Observation:
    execution: Execution
    fact_quality: FactQuality
    dataset_epoch: str | None
    data_version: int | None
    next_action: str | None
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        executions = ("request_recorded", "accepted", "running", "submitted", "verified", "partial", "failed", "unconfirmed")
        qualities = ("resolved", "partial", "unknown", "inconsistent", "not_applicable")
        if self.execution not in executions:
            raise ValueError(f"unknown execution: {self.execution}")
        if self.fact_quality not in qualities:
            raise ValueError(f"unknown fact_quality: {self.fact_quality}")
        if self.data_version is not None and self.data_version < 0:
            raise ValueError("data_version must be non-negative")
        object.__setattr__(self, "evidence", _freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {"execution": self.execution, "fact_quality": self.fact_quality, "dataset_epoch": self.dataset_epoch, "data_version": self.data_version, "next_action": self.next_action, "evidence": _jsonable(self.evidence)}

@dataclass(frozen=True)
class CapabilityResult(Generic[T]):
    operation_id: str | None
    data: T
    observation: Observation
    audit: dict[str, Any]

    def __post_init__(self) -> None:
        if self.observation.execution in ("request_recorded", "accepted", "running", "submitted") and not self.operation_id:
            raise ValueError("operation_id is required for write capability results")
        object.__setattr__(self, "data", _freeze(self.data))
        object.__setattr__(self, "audit", _freeze(self.audit))

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "data": _jsonable(self.data), "observation": self.observation.to_dict(), "audit": _jsonable(self.audit)}
