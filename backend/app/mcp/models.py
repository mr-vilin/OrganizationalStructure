"""独立 MCP wire 模型；不依赖业务包或数据库。"""
from collections.abc import Iterable
from typing import Annotated, Any, Literal
import re
import unicodedata

from pydantic import (AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field,
                      StrictBool, StrictInt, field_validator, model_validator)


class AgentPrincipal(BaseModel):
    """由服务器可信配置绑定的主体，不接受模型输入或客户端身份头。"""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", hide_input_in_errors=True)

    actor_type: Literal["human_agent", "ci_agent"]
    actor_id: str
    environment: Literal["production", "test"]
    run_id: str | None = None
    case_id: str | None = None

    @field_validator("actor_id", "run_id", "case_id")
    @classmethod
    def valid_identifier(cls, value: str | None, info):
        if value is None and info.field_name != "actor_id":
            return value
        if value is None or not 1 <= len(value) <= 191 or any(
            char.isspace() or unicodedata.category(char).startswith("C") for char in value
        ):
            raise ValueError("Invalid agent identifier.")
        return value

    @model_validator(mode="after")
    def valid_context(self):
        if self.environment == "production":
            if self.actor_type == "ci_agent" or (self.run_id and self.run_id.startswith(("test-", "test_"))):
                raise ValueError("Invalid production agent context.")
        elif not self.run_id or not self.run_id.startswith(("test-", "test_")):
            raise ValueError("Invalid test agent context.")
        return self


# 只用于本适配器生成的固定安全消息；不得将上游消息或异常文本插入其中。
_ERROR_MESSAGES = {
    "MCP_SERVICE_UNAUTHORIZED": "MCP service authentication failed.",
    "CAPABILITY_FORBIDDEN": "This capability is not allowed.",
    "CONFIRMATION_REQUIRED": "Trusted human confirmation is required.",
    "UPSTREAM_TIMEOUT": "The outcome is unconfirmed; observe it with get_operation before another write.",
    "UPSTREAM_UNAVAILABLE": "The capability service is unavailable.",
    "UPSTREAM_INVALID_RESPONSE": "The capability service returned an invalid response.",
    "MCP_INTERNAL_ERROR": "The MCP adapter could not complete the request.",
}
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_.]{0,190}\Z")


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool
    confirmation_required: bool = False
    fields: list[dict[str, Any]] = Field(default_factory=list)


class ToolResult(BaseModel):
    operation_id: str | None
    data: Any
    observation: dict[str, Any]
    audit: dict[str, Any]
    error: ToolError | None = None

    @classmethod
    def failure(cls, code: str, *, field_names: Iterable[str] = ()) -> "ToolResult":
        """构造适配器本地失败；不接收异常、任意消息或敏感字段值。"""
        safe_code = code if code in _ERROR_MESSAGES else "MCP_INTERNAL_ERROR"
        return cls(
            operation_id=None, data=None, observation={}, audit={},
            error=ToolError(
                code=safe_code, message=_ERROR_MESSAGES[safe_code], retryable=False,
                confirmation_required=safe_code == "CONFIRMATION_REQUIRED",
                fields=[{"field": name} for name in field_names if isinstance(name, str) and _FIELD_NAME.fullmatch(name)],
            ),
        )

# 独立 HTTP wire 类型：约束只覆盖边界，业务规则仍由内部能力服务判定。


def _route_id(value: str) -> str:
    if value in (".", "..") or any(c in value for c in "/\\?#%") or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid route identifier.")
    return value


Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=191), AfterValidator(_route_id)]
Key = Annotated[str, Field(strict=True, min_length=1, max_length=191)]
Version = Annotated[StrictInt, Field(ge=0)]
PageLimit = Annotated[StrictInt, Field(ge=1, le=500)]
FindLimit = Annotated[StrictInt, Field(ge=1, le=100)]
Cursor = Annotated[str, Field(strict=True, min_length=1)]
Name = Annotated[str, Field(strict=True, min_length=1, max_length=255)]
QueryText = Annotated[str, Field(strict=True, min_length=1)]


class StoreChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    department_id: Identifier
    is_store: StrictBool
    store_code: Annotated[str, Field(max_length=128)] | None = None
    notes: str | None = None


Changes = Annotated[list[StoreChange], Field(min_length=1, max_length=500)]


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    confirmed: StrictBool
