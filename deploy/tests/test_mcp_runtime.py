"""可选侧车部署契约与真实 loopback MCP 就绪探针。"""
import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from time import monotonic, sleep

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def compose():
    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))


def test_sidecar_is_optional_reuses_image_and_has_minimal_environment():
    services = compose()["services"]
    mcp = services["mcp"]
    assert mcp["profiles"] == ["agent"]
    assert mcp["image"] == services["app"]["image"]
    assert mcp["build"] == services["app"]["build"]
    assert mcp["command"] == ["python", "-m", "app.mcp", "--transport", "streamable-http"]
    assert mcp["depends_on"] == {"app": {"condition": "service_healthy"}}
    assert not {"ports", "network_mode", "env_file", "volumes"} & mcp.keys()
    names = {"ORG_MCP_HOST", "ORG_MCP_PORT", "ORG_MCP_SERVICE_TOKEN", "ORG_AGENT_SERVICE_TOKEN",
             "ORG_AGENT_ENVIRONMENT", "ORG_MCP_CAPABILITY_BASE_URL", "ORG_MCP_ACTOR_TYPE",
             "ORG_MCP_ACTOR_ID", "ORG_MCP_RUN_ID", "ORG_MCP_CASE_ID", "ORG_MCP_CONFIRMATION_TIMEOUT"}
    assert set(mcp["environment"]) == names
    for name, value in mcp["environment"].items():
        assert ":?" not in value, "Disabled profile must not add mandatory interpolation"
        if "TOKEN" in name:
            assert value == "${" + name + ":-}"
    assert mcp["environment"]["ORG_MCP_CAPABILITY_BASE_URL"] == "${ORG_MCP_CAPABILITY_BASE_URL:-http://app:8000}"
    assert mcp["healthcheck"]["test"] == ["CMD", "python", "-m", "app.mcp.health"]
    assert mcp["healthcheck"]["timeout"] == "8s"


def test_sidecar_network_cannot_reach_mysql_and_old_network_is_preserved():
    config = compose()
    services = config["services"]
    assert services["mcp"]["networks"] == ["capabilities"]
    assert set(services["app"]["networks"]) == {"default", "capabilities"}
    assert "capabilities" not in services["mysql"].get("networks", ["default"])
    assert "capabilities" not in services["migrate"].get("networks", ["default"])
    assert config["networks"]["capabilities"]["internal"] is True
    assert services["mysql"]["ports"] == ["127.0.0.1:${MYSQL_HOST_PORT:-13307}:3306"]
    assert services["migrate"]["command"] == ["python", "-m", "alembic", "upgrade", "head"]


def test_build_context_and_image_do_not_receive_private_runtime():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".superpowers" in ignored
    assert ".env" in ignored and "**/.venv" in ignored
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ORG_MCP_SERVICE_TOKEN" not in dockerfile
    assert "ORG_AGENT_SERVICE_TOKEN" not in dockerfile
    assert 'CMD ["python", "-m", "deploy.supervise"]' in dockerfile


def clean_environment():
    prefixes = ("ORG_", "FEISHU_", "LARK_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "COZE_", "ARK_", "DASHSCOPE_")
    return {key: value for key, value in os.environ.items() if not key.startswith(prefixes)}


def runtime_environment():
    env = clean_environment()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env.update(ORG_MCP_SERVICE_TOKEN=secrets.token_urlsafe(32), ORG_AGENT_SERVICE_TOKEN=secrets.token_urlsafe(32),
               ORG_MCP_CAPABILITY_BASE_URL="http://127.0.0.1:1", ORG_AGENT_ENVIRONMENT="test",
               ORG_MCP_ACTOR_TYPE="ci_agent", ORG_MCP_ACTOR_ID="runtime-test", ORG_MCP_RUN_ID="test-runtime",
               ORG_MCP_CASE_ID="", ORG_MCP_HOST="0.0.0.0", ORG_MCP_PORT=str(port))
    return env


def run_module(module, env, *args):
    return subprocess.run([sys.executable, "-m", module, *args], cwd=ROOT / "backend", env=env,
                          capture_output=True, text=True, timeout=12,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


@contextmanager
def running_sidecar(env):
    process = subprocess.Popen([sys.executable, "-m", "app.mcp", "--transport", "streamable-http"],
                               cwd=ROOT / "backend", env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    endpoint = f"http://127.0.0.1:{env['ORG_MCP_PORT']}/mcp"
    try:
        deadline = monotonic() + 8
        with httpx.Client(trust_env=False, timeout=0.2) as http:
            while True:
                assert process.poll() is None, "MCP startup failed"
                try:
                    if http.get(endpoint).status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                assert monotonic() < deadline, "Configured host/port did not become ready"
                sleep(0.05)
        yield endpoint
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_real_sidecar_env_listener_auth_discovery_host_origin_and_probe(mode):
    env = runtime_environment()
    with running_sidecar(env) as endpoint:
        with httpx.Client(trust_env=False, timeout=2) as http:
            assert http.get(endpoint).status_code == 401
            assert http.get(endpoint, headers={"Authorization": "Bearer " + env["ORG_AGENT_SERVICE_TOKEN"]}).status_code == 401
            headers = {"Authorization": "Bearer " + env["ORG_MCP_SERVICE_TOKEN"], "Accept": "application/json, text/event-stream"}
            assert http.get(endpoint, headers={**headers, "Host": "untrusted.invalid"}).status_code == 421
            assert http.get(endpoint, headers={**headers, "Origin": "https://untrusted.invalid"}).status_code == 403
        async def discover():
            headers = {"Authorization": "Bearer " + env["ORG_MCP_SERVICE_TOKEN"],
                       "Host": f"mcp:{env['ORG_MCP_PORT']}", "Origin": f"http://mcp:{env['ORG_MCP_PORT']}"}
            async with httpx2.AsyncClient(headers=headers, trust_env=False) as http:
                async with Client(streamable_http_client(endpoint, http_client=http), mode=mode) as client:
                    tools = (await client.list_tools()).tools
                    assert len(tools) == 15
                    assert "get_system_status" in {tool.name for tool in tools}
        asyncio.run(discover())
        success = run_module("app.mcp.health", env)
        assert (success.returncode, success.stdout.strip(), success.stderr) == (0, "MCP_READY", "")
        wrong = {**env, "ORG_MCP_SERVICE_TOKEN": secrets.token_urlsafe(32)}
        failure = run_module("app.mcp.health", wrong)
        assert failure.returncode == 1 and failure.stdout == ""
        assert failure.stderr.strip() == "MCP_NOT_READY"
        assert env["ORG_MCP_SERVICE_TOKEN"] not in success.stdout + success.stderr + failure.stdout + failure.stderr


def test_probe_unavailable_or_invalid_configuration_fails_with_safe_diagnostic():
    env = runtime_environment()
    for scenario in (env, clean_environment(), {**env, "ORG_MCP_PORT": "invalid"},
                     {**env, "ORG_AGENT_SERVICE_TOKEN": env["ORG_MCP_SERVICE_TOKEN"]}):
        result = run_module("app.mcp.health", scenario)
        assert result.returncode == 1
        assert result.stdout == "" and result.stderr.strip() == "MCP_NOT_READY"


def test_runtime_invalid_listener_configuration_is_safe():
    for name, value in (("ORG_MCP_PORT", "0"), ("ORG_MCP_PORT", "65536"), ("ORG_MCP_HOST", "bad/host")):
        env = {**runtime_environment(), name: value}
        result = run_module("app.mcp", env)
        assert result.returncode == 2
        assert "MCP_RUNTIME_NOT_CONFIGURED" in result.stderr and "Traceback" not in result.stderr

@pytest.mark.parametrize("arguments, expected", [([], ("0.0.0.0", 8123)),
                                                  (["--host", "127.0.0.1", "--port", "8124"], ("127.0.0.1", 8124))])
def test_cli_listener_uses_environment_and_explicit_arguments_take_precedence(monkeypatch, arguments, expected):
    from app.mcp import __main__ as cli
    import uvicorn
    for key, value in runtime_environment().items():
        if key.startswith("ORG_"):
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("ORG_MCP_PORT", "8123")
    captured = {}
    monkeypatch.setattr(cli, "create_server", lambda config: object())
    def app(server, **kwargs):
        captured["security"] = kwargs
        return object()
    def run(asgi, **kwargs):
        captured["listener"] = kwargs
    monkeypatch.setattr(cli, "http_app", app)
    monkeypatch.setattr(uvicorn, "run", run)
    assert cli.main(arguments) == 0
    assert (captured["listener"]["host"], captured["listener"]["port"]) == expected
    assert captured["security"] == {"host": expected[0], "port": expected[1]}


def test_probe_stalled_real_http_is_bounded_and_safe():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    finished = threading.Event()
    class StalledHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            finished.wait(10)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), StalledHandler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    env = {**runtime_environment(), "ORG_MCP_PORT": str(http.server_port)}
    start = monotonic()
    try:
        result = run_module("app.mcp.health", env)
        assert result.returncode == 1 and result.stdout == ""
        assert result.stderr.strip() == "MCP_NOT_READY"
        assert monotonic() - start < 8
    finally:
        finished.set()
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("header,status", [("Host", 421), ("Origin", 403)])
@pytest.mark.parametrize("factory", ["configured", "default", "explicit_none", "localhost", "ipv6"])
def test_transport_rejection_does_not_echo_sensitive_headers(header, status, factory, caplog, capsys):
    from pydantic import SecretStr
    from starlette.testclient import TestClient
    from app.mcp.config import MCPSettings, create_server, http_app

    token = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(32)
    credential_url = f"https://operator:{password}@untrusted.invalid/path?access_token={token}"
    settings = MCPSettings(mcp_service_token=SecretStr(secrets.token_urlsafe(32)),
                           agent_service_token=SecretStr(secrets.token_urlsafe(32)),
                           mcp_capability_base_url="http://127.0.0.1:1", agent_environment="test",
                           mcp_actor_type="ci_agent", mcp_actor_id="rejection-test", mcp_run_id="test-rejection")
    server = create_server(settings)
    if factory == "configured":
        app = http_app(server, host="0.0.0.0", port=8001)
        authority = "mcp:8001"
    else:
        options = {}
        if factory == "explicit_none":
            options["transport_security"] = None
        elif factory in {"localhost", "ipv6"}:
            options["host"] = "localhost" if factory == "localhost" else "::1"
        app = server.streamable_http_app(**options)
        authority = "localhost:8001"
    headers = {"Authorization": "Bearer " + settings.mcp_service_token.get_secret_value(),
               "Host": authority, "Origin": "http://" + authority}
    with TestClient(app, base_url="http://" + authority) as client:
        caplog.clear()
        with caplog.at_level("WARNING"):
            result = client.post("/mcp", headers={**headers, header: credential_url}, json={})
        assert result.status_code == status
        output = capsys.readouterr()
        displayed = caplog.text + output.out + output.err + result.text
        assert all(secret not in displayed for secret in (token, password, credential_url)), "Rejected input leaked"
        assert [record.getMessage() for record in caplog.records] == ["MCP_HOST_REJECTED" if header == "Host" else "MCP_ORIGIN_REJECTED"]
        caplog.clear()
        # 认证仍先于 Host/Origin 检查，未经授权的请求不进入 SDK。
        unauthorized = client.post("/mcp", headers={"Host": credential_url, "Origin": credential_url}, json={})
        assert unauthorized.status_code == 401
        assert caplog.records == []
        assert all(secret not in unauthorized.text for secret in (token, password, credential_url))
