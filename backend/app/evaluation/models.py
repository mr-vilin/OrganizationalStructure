"""评测边界模型；冻结字段绑定，不声明嵌套字典深度不可变。"""
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    goal: str
    fixture: dict[str, Any]
    allowed_tools: tuple[str, ...]
    expected_state: dict[str, Any]
    forbidden_effects: tuple[dict[str, Any], ...]
    timeout_seconds: int
    max_tool_calls: int


@dataclass(frozen=True)
class ToolTraceEvent:
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    result_code: str | None
    operation_id: str | None
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class AgentRunContext:
    run_id: str
    case_id: str
    actor_id: str
    environment: Literal["test"]


@dataclass(frozen=True)
class AgentRun:
    final_text: str
    trace: tuple[ToolTraceEvent, ...]
    terminal_observation: dict[str, Any]


@dataclass(frozen=True)
class EvaluationReport:
    case_id: str
    run_id: str
    hard_passed: bool
    hard_failures: tuple[str, ...]
    soft_scores: dict[str, float]
    evidence: dict[str, Any]
    trace: tuple[ToolTraceEvent, ...]
