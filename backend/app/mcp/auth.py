"""MCP 入站独立令牌认证与可信主体校验。"""
from collections.abc import Mapping
import hmac
from typing import Any, Literal

from pydantic import SecretStr, ValidationError

from .models import AgentPrincipal


class AuthenticationError(ValueError):
    code = "MCP_SERVICE_UNAUTHORIZED"

    def __init__(self):
        super().__init__("MCP service authentication failed.")


def verify_service_token(value: str, expected: SecretStr) -> bool:
    """精确比较独立 MCP 入站令牌；空配置禁用认证。"""
    if not isinstance(value, str) or not isinstance(expected, SecretStr):
        return False
    secret = expected.get_secret_value()
    if not secret.strip() or not value.strip():
        return False
    try:
        return hmac.compare_digest(value.encode("utf-8"), secret.encode("utf-8"))
    except UnicodeEncodeError:
        return False


def validate_principal(
    value: AgentPrincipal | Mapping[str, Any], *, environment: Literal["production", "test"],
) -> AgentPrincipal:
    """仅供可信配置调用方使用；重新校验以防 model_construct 绕过验证。"""
    try:
        raw = value.model_dump() if isinstance(value, AgentPrincipal) else value
        principal = AgentPrincipal.model_validate(raw)
    except (ValidationError, ValueError, TypeError):
        raise AuthenticationError() from None
    if environment not in ("production", "test") or principal.environment != environment:
        raise AuthenticationError()
    return principal


def authenticate(
    authorization: str | None, *, expected_token: SecretStr,
    principal: AgentPrincipal | Mapping[str, Any], environment: Literal["production", "test"],
) -> AgentPrincipal:
    """验证单一入站 Authorization；身份只取可信参数，不读取客户端身份头。

    Task 4 的 HTTP 边界须先拒绝重复 Authorization；expected_token 来自
    ORG_MCP_SERVICE_TOKEN，绝不能传入 ORG_AGENT_SERVICE_TOKEN。
    """
    if not isinstance(authorization, str):
        raise AuthenticationError()
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or any(char.isspace() for char in token):
        raise AuthenticationError()
    if not verify_service_token(token, expected_token):
        raise AuthenticationError()
    return validate_principal(principal, environment=environment)
