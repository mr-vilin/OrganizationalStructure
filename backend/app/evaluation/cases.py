"""schema v1 的安全 YAML 边界；不连接数据库或加载业务运行时。"""
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml

from app.mcp.policy import TOOL_LEVELS
from .models import EvaluationCase


class _CaseDocument(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    schema_version: Annotated[int, Field(ge=1, le=1)]
    case_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=191)]
    goal: str
    fixture: dict[str, Any]
    allowed_tools: Annotated[tuple[str, ...], Field(strict=False, min_length=1)]
    expected_state: Annotated[dict[str, Any], Field(min_length=1)]
    forbidden_effects: Annotated[tuple[dict[str, Any], ...], Field(strict=False)]
    timeout_seconds: Annotated[int, Field(gt=0)]
    max_tool_calls: Annotated[int, Field(gt=0)]

    @field_validator("goal")
    @classmethod
    def nonempty_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be blank")
        return value

    @field_validator("allowed_tools")
    @classmethod
    def known_unique_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(tool not in TOOL_LEVELS for tool in value):
            raise ValueError("allowed_tools contains an unknown MCP tool")
        if len(value) != len(set(value)):
            raise ValueError("allowed_tools contains duplicate tools")
        return value

    @field_validator("forbidden_effects")
    @classmethod
    def nonempty_effects(cls, value: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        if any(not effect for effect in value):
            raise ValueError("forbidden_effects entries must not be empty")
        return value

    def to_case(self) -> EvaluationCase:
        return EvaluationCase(**self.model_dump(exclude={"schema_version"}))


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """拒绝 YAML 重复键，避免静默覆盖版本或用例条件。"""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("YAML mapping keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_case(path: str | Path) -> EvaluationCase:
    """读取 UTF-8 schema_version=1 文档；结构错误抛出 ValueError。"""
    try:
        document = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise ValueError("Invalid or unsafe case YAML") from exc
    return _CaseDocument.model_validate(document).to_case()


def validate_case(case: EvaluationCase) -> EvaluationCase:
    """重新校验直接构造的固定模型，并返回独立的已验证副本。"""
    if not isinstance(case, EvaluationCase):
        raise ValueError("Expected an EvaluationCase")
    return _CaseDocument.model_validate({"schema_version": 1, **asdict(case)}).to_case()


def load_cases(paths: Iterable[str | Path]) -> tuple[EvaluationCase, ...]:
    """仅在本次 suite 内拒绝重复 ID；单文件加载没有全局状态。"""
    result = []
    seen = set()
    for path in paths:
        case = load_case(path)
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)
        result.append(case)
    return tuple(result)
