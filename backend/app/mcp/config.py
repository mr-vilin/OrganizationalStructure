"""Sidecar 独立可信配置；不加载后台数据库、飞书或模型设置。"""
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .auth import validate_principal
from .client import CapabilityHttpClient
from .models import AgentPrincipal


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORG_", extra="ignore", hide_input_in_errors=True, env_ignore_empty=True)
    mcp_host: str = Field(default="127.0.0.1", min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    mcp_port: int = Field(default=8001, ge=1, le=65535)
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


def http_app(server, *, host: str, port: int):
    """部署仅接受当前端口的回环、Compose 服务名及显式监听名。"""
    from mcp.server.transport_security import TransportSecuritySettings
    hosts = {"127.0.0.1", "localhost", "[::1]", "mcp"}
    if host not in {"0.0.0.0", "::"}:
        hosts.add(f"[{host}]" if ":" in host else host)
    authorities = sorted({f"{name}:{port}" for name in hosts} | (hosts if port == 80 else set()))
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                         allowed_hosts=authorities,
                                         allowed_origins=[f"http://{name}" for name in authorities])
    return server.streamable_http_app(host=host, transport_security=security)


def create_app():
    """uvicorn ASGI factory；uvicorn 自身的监听参数仍需调用者显式传入。"""
    try:
        config = MCPSettings()
    except ValueError:
        raise ValueError("MCP_RUNTIME_NOT_CONFIGURED") from None
    return http_app(create_server(config), host=config.mcp_host, port=config.mcp_port)
