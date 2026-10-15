"""Sidecar 独立可信配置；不加载后台数据库、飞书或模型设置。"""
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .auth import validate_principal
from .client import CapabilityHttpClient
from .models import AgentPrincipal


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORG_", extra="ignore", hide_input_in_errors=True)
    mcp_service_token: SecretStr
    agent_service_token: SecretStr
    mcp_capability_base_url: str
    agent_environment: Literal["production", "test"]
    mcp_actor_type: Literal["human_agent", "ci_agent"]
    mcp_actor_id: str
    mcp_run_id: str | None = None
    mcp_case_id: str | None = None
    mcp_confirmation_timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def separate_tokens(self):
        if self.mcp_service_token.get_secret_value() == self.agent_service_token.get_secret_value():
            raise ValueError("Independent service tokens are required.")
        return self

    def principal(self):
        return validate_principal(AgentPrincipal(actor_type=self.mcp_actor_type, actor_id=self.mcp_actor_id,
                                  environment=self.agent_environment, run_id=self.mcp_run_id,
                                  case_id=self.mcp_case_id), environment=self.agent_environment)


def create_server(settings: MCPSettings | None = None):
    """真实部署/测试工厂；缺配置只抛固定安全错误。"""
    from . import policy
    from .server import build_server
    from .trace import Tracer
    try:
        config = settings if settings is not None else MCPSettings()
        principal = config.principal()
        # 在创建 HTTP client 前校验所有身份、token、超时，避免失败启动留下资源。
        token = config.mcp_service_token.get_secret_value()
        if not token or not token.isascii() or any(c.isspace() or ord(c) < 33 for c in token):
            raise ValueError()
        client = CapabilityHttpClient(config.mcp_capability_base_url, config.agent_service_token,
                                      environment=config.agent_environment)
        return build_server(client, policy, Tracer(), principal=principal, inbound_token=config.mcp_service_token,
                            environment=config.agent_environment, confirmation_timeout=config.mcp_confirmation_timeout)
    except (ValueError, TypeError):
        raise ValueError("MCP_RUNTIME_NOT_CONFIGURED") from None


def create_app():
    """uvicorn app.mcp.config:create_app --factory；认证覆盖 /mcp 所有请求。"""
    return create_server().streamable_http_app()
