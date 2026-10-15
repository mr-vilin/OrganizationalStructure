"""用官方协议初始化及工具发现验证就绪；不调用业务工具或数据库。"""
import asyncio
import logging
import sys

from .config import MCPSettings
from .policy import TOOL_LEVELS


async def check_ready(config: MCPSettings) -> None:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    host = config.mcp_host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1" if host == "0.0.0.0" else "[::1]"
    elif ":" in host:
        host = f"[{host}]"
    endpoint = f"http://{host}:{config.mcp_port}/mcp"
    token = config.mcp_service_token.get_secret_value()
    if not token or not token.isascii() or any(c.isspace() or ord(c) < 33 for c in token):
        raise ValueError()
    async with asyncio.timeout(4):
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"},
                                     timeout=2, trust_env=False) as http:
            async with Client(streamable_http_client(endpoint, http_client=http)) as client:
                tools = (await client.list_tools()).tools
                if len(tools) != len(TOOL_LEVELS) or {tool.name for tool in tools} != set(TOOL_LEVELS):
                    raise ValueError()


def main() -> int:
    # 独立 CLI 不输出 SDK/HTTP 异常原文，令牌、响应及配置不进入探针日志。
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(check_ready(MCPSettings()))
    except Exception:
        print("MCP_NOT_READY", file=sys.stderr)
        return 1
    print("MCP_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
