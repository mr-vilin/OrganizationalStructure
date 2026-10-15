"""MCP SDK 边界：业务工具及生产接线由 Task 4 完成。"""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from app.mcp.server import build_server


@pytest.mark.parametrize("mode, protocol_version", [("legacy", "2025-11-25"), (None, "2026-07-28")])
def test_sdk_connects_and_discovers_empty_stage_one_server(mode, protocol_version):
    from mcp import Client
    from mcp.server import MCPServer

    server = build_server(object(), object(), object())
    assert isinstance(server, MCPServer)

    async def discover():
        options = {"mode": mode} if mode else {"raise_exceptions": True}
        async with Client(server, **options) as client:
            assert client.protocol_version == protocol_version
            assert (await client.list_tools()).tools == []

    asyncio.run(discover())


@asynccontextmanager
async def serve_http(server):
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]
    runner = uvicorn.Server(uvicorn.Config(
        server.streamable_http_app(), log_level="error", access_log=False, ws="none",
    ))
    task = asyncio.create_task(runner.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not runner.started:
                if task.done():
                    await task
                    raise RuntimeError("MCP HTTP server exited before startup")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        runner.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            listener.close()


@pytest.mark.parametrize("mode, protocol_version", [("legacy", "2025-11-25"), ("auto", "2026-07-28")])
def test_streamable_http_supports_initialize_and_default_discovery(mode, protocol_version):
    from mcp import Client

    async def discover():
        server = build_server(object(), object(), object())
        async with serve_http(server) as endpoint:
            async with Client(endpoint, mode=mode, read_timeout_seconds=5) as client:
                assert client.protocol_version == protocol_version
                assert client.server_info.name == "organization-capabilities"
                assert (await client.list_tools()).tools == []

    asyncio.run(discover())


def run_python(*arguments):
    excluded = (
        "ORG_", "FEISHU_", "LARK_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_",
        "COZE_", "ARK_", "DASHSCOPE_",
    )
    environment = {key: value for key, value in os.environ.items() if not key.startswith(excluded)}
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )


def run_cli(*arguments):
    return run_python("-m", "app.mcp", *arguments)


def test_factory_does_not_import_business_or_database_modules():
    result = run_python("-c", """
import sys
from app.mcp import build_server
build_server(object(), object(), object())
for prefix in ("app.capabilities", "app.persistence", "sqlalchemy", "app.main"):
    assert not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules), prefix
""")
    assert result.returncode == 0, result.stderr


def test_cli_help_lists_transport_host_and_port():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "streamable-http" in result.stdout
    assert "--host" in result.stdout
    assert "--port" in result.stdout


def test_cli_fails_closed_before_live_dependencies_are_wired():
    result = run_cli("--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8765")
    assert result.returncode == 2
    assert "MCP_RUNTIME_NOT_CONFIGURED" in result.stderr
    assert "Traceback" not in result.stderr
