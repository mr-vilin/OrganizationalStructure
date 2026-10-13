"""Immutable contracts shared by capability adapters and services."""
from dataclasses import asdict, dataclass
from typing import Any, Generic, Literal, TypeVar

ActorType = Literal["human_agent", "ci_agent"]
Environment = Literal["production", "test"]
Execution = Literal["request_recorded", "accepted", "running", "submitted", "verified", "partial", "failed", "unconfirmed"]
FactQuality = Literal["resolved", "partial", "unknown", "inconsistent", "not_applicable"]
T = TypeVar("T")

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class CapabilityResult(Generic[T]):
    operation_id: str | None
    data: T
    observation: Observation
    audit: dict[str, Any]

    def __post_init__(self) -> None:
        if self.observation.execution in ("request_recorded", "accepted", "running", "submitted") and not self.operation_id:
            raise ValueError("operation_id is required for write capability results")

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "data": self.data, "observation": self.observation.to_dict(), "audit": self.audit}
