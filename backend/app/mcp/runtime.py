"""SDK 生命周期与 HTTP 身份边界；不持有业务状态或自行实现确认协议。"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import math

from mcp.server import MCPServer
from mcp.server.request_state import RequestStateSecurity
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr
from starlette.responses import JSONResponse

from .auth import AuthenticationError, authenticate, validate_principal
from .models import ToolResult


_confirmation_timer: ContextVar[asyncio.Timeout | None] = ContextVar("mcp_confirmation_timer", default=None)


def finish_confirmation_wait():
    """工具体开始后由内部 HTTP client 自身的 timeout 管理提交结果。"""
    timer = _confirmation_timer.get()
    if timer is not None:
        timer.reschedule(None)


class ServiceAuthentication:
    def __init__(self, app, *, token, principal, environment):
        self.app, self.token, self.principal, self.environment = app, token, principal, environment

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            values = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            try:
                if len(values) != 1:
                    raise AuthenticationError()
                authenticate(values[0].decode("latin-1"), expected_token=self.token,
                             principal=self.principal, environment=self.environment)
            except AuthenticationError:
                await JSONResponse({"error": {"code": "MCP_SERVICE_UNAUTHORIZED"}}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class CapabilityServer(MCPServer):
    """所有 HTTP app 都带身份认证；in-process Client 仅供可信嵌入和 harness。"""
    def __init__(self, *, client, principal, inbound_token, environment, confirmation_timeout, tools):
        try:
            principal = validate_principal(principal, environment=environment)
            if (not isinstance(inbound_token, SecretStr) or not inbound_token.get_secret_value().isascii()
                    or not inbound_token.get_secret_value() or any(c.isspace() or ord(c) < 33 for c in inbound_token.get_secret_value())
                    or isinstance(confirmation_timeout, bool) or not math.isfinite(confirmation_timeout)
                    or confirmation_timeout <= 0):
                raise ValueError()
            if not all(callable(getattr(client, method, None)) for method in ("read", "call", "aclose")):
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("MCP_RUNTIME_NOT_CONFIGURED") from None
        self._inbound_token = inbound_token
        self._principal = principal
        self._environment = environment

        @asynccontextmanager
        async def lifespan(_server):
            try:
                yield {}
            finally:
                await client.aclose()

        async def bound_call(ctx, call_next):
            if ctx.method != "tools/call":
                return await call_next(ctx)
            try:
                async with asyncio.timeout(confirmation_timeout) as timer:
                    token = _confirmation_timer.set(timer)
                    try:
                        return await call_next(ctx)
                    finally:
                        _confirmation_timer.reset(token)
            except TimeoutError:
                result = ToolResult.failure("CONFIRMATION_REQUIRED")
                return CallToolResult(content=[TextContent(type="text", text=result.model_dump_json())],
                                      structured_content=result.model_dump(), is_error=True)

        # SDK seals/binds each modern confirmation to exact tool arguments; ttl also
        # bounds human wait between HTTP rounds. Legacy waits are bounded above.
        security = RequestStateSecurity.ephemeral(ttl=confirmation_timeout)
        security.bind_principal = lambda _ctx: principal.model_dump_json()
        super().__init__(name="organization-capabilities", version="0.1.0", tools=tools,
                         instructions="使用版本与幂等键执行能力；写入超时后先调用 get_operation 观察。",
                         lifespan=lifespan, middleware=[bound_call], request_state_security=security)

    def streamable_http_app(self, **kwargs):
        app = super().streamable_http_app(**kwargs)
        app.add_middleware(ServiceAuthentication, token=self._inbound_token,
                           principal=self._principal, environment=self._environment)
        return app
