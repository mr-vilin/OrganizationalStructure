"""真实 SDK 目录、schema、认证与工具调用契约。"""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys

import httpx
import httpx2
from mcp.client.streamable_http import streamable_http_client
from mcp import Client
from mcp.types import ElicitResult
from pydantic import SecretStr
import pytest

from app.mcp import policy
from app.mcp.client import CapabilityHttpClient
from app.mcp.models import AgentPrincipal
from app.mcp.server import build_server
from app.mcp.trace import Tracer

TOKEN = SecretStr("synthetic-mcp-token")
SUCCESS = {"operation_id": "op-1", "data": {"data": [], "meta": {"data_version": 7}},
           "observation": {"execution_status": "succeeded", "fact_quality": "partial"}, "audit": {}}


def make_server(requests, *, production=False, timeout=60):
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=SUCCESS)
    principal = AgentPrincipal(actor_type="human_agent" if production else "ci_agent", actor_id="trusted-agent",
                               environment="production" if production else "test",
                               run_id=None if production else "test-sdk", case_id="case-a")
    upstream = CapabilityHttpClient("http://internal", SecretStr("synthetic-internal-token"),
                                    environment=principal.environment, transport=httpx.MockTransport(handle))
    return build_server(upstream, policy, Tracer(), principal=principal, inbound_token=TOKEN,
                        environment=principal.environment, confirmation_timeout=timeout)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_sdk_catalog_and_hidden_confirmation(mode):
    async def scenario():
        async with Client(make_server([]), mode=mode) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(tools) == set(policy.TOOL_LEVELS)
            for name, tool in tools.items():
                assert tool.output_schema["properties"].keys() >= {"operation_id", "data", "observation", "audit", "error"}
                assert not {"approved", "approval_token", "actor_id", "confirmation"} & tool.input_schema["properties"].keys()
            assert tools["find_departments"].input_schema["properties"]["limit"]["maximum"] == 100
            assert tools["apply_store_changes"].input_schema["properties"]["changes"]["maxItems"] == 500
            assert set(tools["apply_store_changes"].input_schema["required"]) == {"changes", "expected_epoch", "expected_version", "idempotency_key"}
            assert set(tools["request_sync"].input_schema["properties"]["job_type"]["enum"]) == {"initialize", "reconcile", "full", "subtree"}
            assert "actor" in tools["get_change_logs"].input_schema["properties"]
    asyncio.run(scenario())


@asynccontextmanager
async def serve_http(server):
    import uvicorn
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    runner = uvicorn.Server(uvicorn.Config(server.streamable_http_app(), log_level="error", access_log=False, ws="none"))
    task = asyncio.create_task(runner.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not runner.started:
                if task.done():
                    await task
                    raise RuntimeError("MCP HTTP server exited before startup")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
    finally:
        runner.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            listener.close()


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_http_authentication_discovery_and_identity(mode):
    async def scenario():
        requests = []
        async with serve_http(make_server(requests)) as endpoint:
            async with httpx.AsyncClient() as http:
                for headers in ([], [("Authorization", "Bearer synthetic-internal-token")],
                                [("Authorization", "Bearer synthetic-mcp-token"), ("authorization", "Bearer synthetic-mcp-token")]):
                    response = await http.post(endpoint, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "server/discover"})
                    assert response.status_code == 401
                    assert "synthetic" not in response.text
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer synthetic-mcp-token", "X-Agent-Actor-Id": "forged", "X-Agent-Environment": "production", "X-Agent-Approved": "true"}) as http, Client(streamable_http_client(endpoint, http_client=http), mode=mode) as client:
                assert len((await client.list_tools()).tools) == 15
                result = await client.call_tool("get_system_status", {})
                assert result.structured_content == {**SUCCESS, "error": None}
            assert requests[0].headers["X-Agent-Actor-Id"] != "forged"
            assert requests[0].headers["X-Agent-Environment"] == "test"
    asyncio.run(scenario())


def run_python(*arguments):
    excluded = ("ORG_", "FEISHU_", "LARK_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "COZE_", "ARK_", "DASHSCOPE_")
    environment = {key: value for key, value in os.environ.items() if not key.startswith(excluded)}
    return subprocess.run([sys.executable, *arguments], cwd=Path(__file__).resolve().parents[1], env=environment,
                          capture_output=True, text=True, encoding="utf-8", timeout=10)


def test_factory_fails_closed_without_identity_and_token():
    with pytest.raises(ValueError, match="MCP_RUNTIME_NOT_CONFIGURED"):
        build_server(object(), policy, Tracer())


def test_factory_does_not_import_business_or_database_modules():
    result = run_python("-c", """
import sys
from app.mcp import build_server
for prefix in ("app.capabilities", "app.persistence", "sqlalchemy", "app.main"):
    assert not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules), prefix
""")
    assert result.returncode == 0, result.stderr


def test_cli_help_lists_transport_host_and_port():
    result = run_python("-m", "app.mcp", "--help")
    assert result.returncode == 0
    assert "streamable-http" in result.stdout and "--host" in result.stdout and "--port" in result.stdout


def test_cli_fails_closed_without_configuration():
    result = run_python("-m", "app.mcp")
    assert result.returncode == 2
    assert "MCP_RUNTIME_NOT_CONFIGURED" in result.stderr and "Traceback" not in result.stderr


TOOL_CALLS = [
    ("get_system_status", {}, "GET", "/status"),
    ("find_departments", {"name": "门店", "limit": 10}, "GET", "/departments"),
    ("get_department", {"department_id": "dep-1"}, "GET", "/departments/dep-1"),
    ("list_employees", {"department_id": "dep-1", "include_descendants": True, "dataset_epoch": "epoch", "data_version": 7}, "GET", "/employees"),
    ("get_employee", {"employee_id": "emp-1"}, "GET", "/employees/emp-1"),
    ("list_stores", {"include_inactive": True, "cursor": "opaque", "data_version": 7}, "GET", "/stores"),
    ("get_store", {"store_id": "store-1"}, "GET", "/stores/store-1"),
    ("list_store_employees", {"store_id": "store-1", "membership": "primary"}, "GET", "/stores/store-1/employees"),
    ("get_change_logs", {"actor": "business-filter", "committed_after": "2026-10-01T00:00:00+08:00", "cursor": "opaque", "dataset_epoch": "epoch", "data_version": 7}, "GET", "/change-logs"),
    ("get_sync_job", {"job_id": "job-1"}, "GET", "/sync/jobs/job-1"),
    ("get_operation", {"operation_id": "op-1"}, "GET", "/operations/op-1"),
    ("get_operation", {"idempotency_key": "lookup&key"}, "GET", "/operations/lookup"),
    ("preview_store_changes", {"changes": [{"department_id": "dep-1", "is_store": True}], "expected_version": 7}, "POST", "/stores/batch/preview"),
    ("apply_store_changes", {"changes": [{"department_id": "dep-1", "is_store": True, "notes": None}], "expected_epoch": "epoch", "expected_version": 7, "idempotency_key": "key"}, "POST", "/stores/batch/apply"),
    ("request_sync", {"job_type": "subtree", "root_department_id": "dep-1", "idempotency_key": "key"}, "POST", "/sync/jobs"),
    ("retry_sync_job", {"job_id": "job-1", "idempotency_key": "key"}, "POST", "/sync/jobs/job-1/retry"),
]
WRITES = [entry for entry in TOOL_CALLS if entry[0] in {"apply_store_changes", "request_sync", "retry_sync_job"}]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,arguments,method,path", TOOL_CALLS)
def test_official_sdk_routes_all_tools_and_keeps_results(mode, name, arguments, method, path):
    async def scenario():
        requests = []
        async with Client(make_server(requests), mode=mode) as client:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result
            assert result.structured_content == {**SUCCESS, "error": None}
        assert len(requests) == 1
        request = requests[0]
        assert request.method == method and request.url.path == "/internal/capabilities" + path
        if method == "GET":
            for key, value in arguments.items():
                if key in {"department_id", "employee_id", "store_id", "job_id", "operation_id"} and value in path.split("/"):
                    continue
                assert request.url.params[key] == (str(value).lower() if isinstance(value, bool) else str(value))
            assert "invoke" not in request.url.params
        else:
            import json
            expected = {k: v for k, v in arguments.items() if k != "job_id"}
            assert json.loads(request.content) == expected
        assert request.headers["X-Agent-Approved"] == ("true" if name in {w[0] for w in WRITES} else "false")
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,arguments,_method,_path", WRITES)
@pytest.mark.parametrize("action,answer,allowed", [("accept", True, True), ("accept", False, False),
                                                 ("decline", None, False), ("cancel", None, False),
                                                 ("accept", "true", False), ("accept", 1, False)])
def test_production_resolve_requires_strict_human_accept(mode, name, arguments, _method, _path, action, answer, allowed):
    async def scenario():
        requests, questions = [], []
        async def elicit(_context, params):
            questions.append(params)
            return ElicitResult(action=action, content={"confirmed": answer} if action == "accept" else None)
        async with Client(make_server(requests, production=True), mode=mode, elicitation_callback=elicit) as client:
            result = await client.call_tool(name, arguments)
            if allowed:
                assert result.structured_content["error"] is None
                assert requests[0].headers["X-Agent-Approved"] == "true"
            else:
                assert result.is_error or result.structured_content["error"]["code"] == "CONFIRMATION_REQUIRED"
        assert len(questions) == 1 and len(requests) == int(allowed)
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,arguments,_method,_path", WRITES)
def test_missing_elicitation_capability_does_not_write(mode, name, arguments, _method, _path):
    async def scenario():
        requests = []
        async with Client(make_server(requests, production=True), mode=mode) as client:
            try:
                result = await client.call_tool(name, arguments)
                assert result.is_error or result.structured_content["error"]
            except Exception as error:
                from mcp.shared.exceptions import MCPError
                assert isinstance(error, MCPError)
        assert requests == []
    asyncio.run(scenario())


INVALID_CALLS = [
    ("find_departments", {"limit": 101}), ("find_departments", {"limit": True}),
    ("find_departments", {"name": "x" * 256}), ("find_departments", {"name": "a", "department_id": "b"}),
    ("find_departments", {"name": "a", "cursor": "opaque"}),
    ("get_department", {"department_id": "../status"}), ("get_department", {"department_id": "x" * 192}),
    ("list_employees", {"data_version": True}), ("list_employees", {"data_version": -1}),
    ("get_change_logs", {"cursor": 123}), ("get_change_logs", {"committed_after": "2026-01-01T00:00:00"}),
    ("get_change_logs", {"action": "replace"}), ("list_store_employees", {"store_id": "s", "membership": "unknown"}),
    ("get_operation", {}), ("get_operation", {"operation_id": "op", "idempotency_key": "key"}),
    ("preview_store_changes", {"changes": [], "expected_version": 7}),
    ("preview_store_changes", {"changes": [{"department_id": "d", "is_store": 1}], "expected_version": 7}),
    ("preview_store_changes", {"changes": [{"department_id": "d", "is_store": True}] * 501, "expected_version": 7}),
    ("apply_store_changes", {"changes": [{"department_id": "d", "is_store": True}], "expected_version": 7, "idempotency_key": "key"}),
    ("apply_store_changes", {"changes": [{"department_id": "d", "is_store": True}], "expected_epoch": "e", "idempotency_key": "key"}),
    ("apply_store_changes", {"changes": [{"department_id": "d", "is_store": True}], "expected_epoch": "e", "expected_version": True, "idempotency_key": "key"}),
    ("request_sync", {"job_type": "full"}), ("request_sync", {"job_type": "bad", "idempotency_key": "key"}),
    ("request_sync", {"job_type": "subtree", "idempotency_key": "key"}),
    ("request_sync", {"job_type": "full", "root_department_id": "d", "idempotency_key": "key"}),
    ("request_sync", {"job_type": "full", "idempotency_key": "k" * 192}),
    ("request_sync", {"job_type": "full", "idempotency_key": "key", "approved": True}),
    ("request_sync", {"job_type": "full", "idempotency_key": "key", "confirmation": {"action": "accept", "data": {"confirmed": True}}}),
    ("get_system_status", {"actor_id": "forged", "environment": "test"}),
]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,arguments", INVALID_CALLS)
def test_invalid_schema_never_reaches_http(mode, name, arguments):
    async def scenario():
        requests = []
        async with Client(make_server(requests, production=True), mode=mode) as client:
            result = await client.call_tool(name, arguments)
            assert result.is_error
        assert requests == []
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_sensitive_validation_input_not_echoed_or_traced(mode, caplog, capfd):
    async def scenario():
        requests = []
        async with Client(make_server(requests), mode=mode) as client:
            result = await client.call_tool("apply_store_changes", {"changes": [{"department_id": "d", "is_store": "SYNTHETIC_SECRET_MARKER"}], "expected_epoch": "e", "expected_version": "SYNTHETIC_SECRET_MARKER", "idempotency_key": "k"})
            assert result.is_error
            assert "SYNTHETIC_SECRET_MARKER" not in result.model_dump_json()
        assert requests == []
    asyncio.run(scenario())
    assert "SYNTHETIC_SECRET_MARKER" not in caplog.text
    output = capfd.readouterr()
    assert "SYNTHETIC_SECRET_MARKER" not in output.out + output.err


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,arguments,_method,_path", WRITES)
def test_confirmation_timeout_never_writes(mode, name, arguments, _method, _path):
    async def scenario():
        requests = []
        async def delayed(_context, _params):
            await asyncio.sleep(0.15)
            return ElicitResult(action="accept", content={"confirmed": True})
        async with Client(make_server(requests, production=True, timeout=0.05), mode=mode, elicitation_callback=delayed) as client:
            try:
                result = await client.call_tool(name, arguments)
                assert result.is_error or result.structured_content["error"]
            except Exception as error:
                from mcp.shared.exceptions import MCPError
                assert isinstance(error, MCPError)
        assert requests == []
    asyncio.run(scenario())


MUTATIONS = [
    (WRITES[0], "changes", [{"department_id": "other", "is_store": False}]),
    (WRITES[0], "expected_epoch", "another-epoch"),
    (WRITES[0], "expected_version", 8),
    (WRITES[0], "idempotency_key", "another-key"),
    (WRITES[1], "job_type", "full"),
    (WRITES[1], "root_department_id", "another-root"),
    (WRITES[1], "idempotency_key", "another-key"),
    (WRITES[2], "job_id", "another-job"),
    (WRITES[2], "idempotency_key", "another-key"),
    (WRITES[0], "tool", "retry_sync_job"),
    (WRITES[0], "state", "forged-state"),
]


@pytest.mark.parametrize("entry,key,value", MUTATIONS)
def test_sdk_sealed_confirmation_binds_tool_and_all_write_arguments(entry, key, value):
    from mcp.types import InputRequiredResult
    from mcp.shared.exceptions import MCPError
    async def scenario():
        requests = []
        async def elicit(_context, _params):
            raise AssertionError("Manual protocol test must not auto-answer")
        async with Client(make_server(requests, production=True), elicitation_callback=elicit) as client:
            name, arguments, _, _ = entry
            pending = await client.session.call_tool(name, arguments, allow_input_required=True)
            assert isinstance(pending, InputRequiredResult) and pending.request_state
            answers = {k: ElicitResult(action="accept", content={"confirmed": True}) for k in pending.input_requests}
            changed = {**arguments, key: value} if key not in {"state", "tool"} else arguments
            target = value if key == "tool" else name
            state = value if key == "state" else pending.request_state
            with pytest.raises(MCPError):
                await client.session.call_tool(target, changed, request_state=state, input_responses=answers, allow_input_required=True)
            assert requests == []
            # Exact original request still resumes once; there is no application-built signing scheme.
            result = await client.session.call_tool(name, arguments, request_state=pending.request_state,
                                                   input_responses=answers, allow_input_required=True)
            assert result.structured_content["error"] is None
            assert len(requests) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("name,arguments,_method,_path", WRITES)
def test_http_production_elicitation_is_hidden_and_authenticated(mode, name, arguments, _method, _path):
    async def scenario():
        requests = []
        async def elicit(_context, _params):
            return ElicitResult(action="accept", content={"confirmed": True})
        async with serve_http(make_server(requests, production=True)) as endpoint:
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer synthetic-mcp-token"}) as http:
                async with Client(streamable_http_client(endpoint, http_client=http), mode=mode, elicitation_callback=elicit) as client:
                    result = await client.call_tool(name, arguments)
                    assert result.structured_content["error"] is None
        assert len(requests) == 1 and requests[0].headers["X-Agent-Approved"] == "true"
    asyncio.run(scenario())


def test_config_rejects_incomplete_context_shared_tokens_and_production_ci(monkeypatch):
    from app.mcp.config import MCPSettings, create_server
    for key in tuple(os.environ):
        if key.startswith("ORG_"):
            monkeypatch.delenv(key)
    with pytest.raises(ValueError, match="MCP_RUNTIME_NOT_CONFIGURED"):
        create_server()
    settings = {"mcp_service_token": "synthetic-mcp-token", "agent_service_token": "synthetic-internal-token",
                "mcp_capability_base_url": "http://internal", "agent_environment": "production",
                "mcp_actor_type": "ci_agent", "mcp_actor_id": "agent"}
    with pytest.raises(ValueError, match="MCP_RUNTIME_NOT_CONFIGURED"):
        create_server(MCPSettings(**settings))
    with pytest.raises(ValueError):
        MCPSettings(**{**settings, "agent_service_token": "synthetic-mcp-token"})
    with pytest.raises(ValueError, match="MCP_RUNTIME_NOT_CONFIGURED"):
        create_server(MCPSettings(**{**settings, "agent_environment": "test", "mcp_run_id": "invalid"}))


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_sdk_lifespan_closes_owned_internal_client(mode):
    async def scenario():
        owned = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=SUCCESS)))
        upstream = CapabilityHttpClient("http://internal", SecretStr("synthetic-internal-token"), environment="test", client=owned)
        principal = AgentPrincipal(actor_type="ci_agent", actor_id="agent", environment="test", run_id="test-life")
        server = build_server(upstream, policy, Tracer(), principal=principal, environment="test", inbound_token=TOKEN)
        async with Client(server, mode=mode) as client:
            await client.call_tool("get_system_status", {})
            assert not owned.is_closed
        assert owned.is_closed
    asyncio.run(scenario())

@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_confirmation_deadline_does_not_cancel_confirmed_http_write(mode):
    async def scenario():
        requests = []
        async def slow_backend(request):
            requests.append(request)
            await asyncio.sleep(0.12)
            return httpx.Response(200, json=SUCCESS)
        async def elicit(_context, _params):
            return ElicitResult(action="accept", content={"confirmed": True})
        upstream = CapabilityHttpClient("http://internal", SecretStr("synthetic-internal-token"), environment="production",
                                        transport=httpx.MockTransport(slow_backend))
        server = build_server(upstream, policy, Tracer(), principal=AgentPrincipal(actor_type="human_agent", actor_id="a", environment="production"),
                              environment="production", inbound_token=TOKEN, confirmation_timeout=0.05)
        async with Client(server, mode=mode, elicitation_callback=elicit) as client:
            result = await client.call_tool("request_sync", {"job_type": "full", "idempotency_key": "key"})
            assert result.structured_content["error"] is None
        assert len(requests) == 1
    asyncio.run(scenario())

@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_official_sdk_through_actual_internal_router_with_trusted_context(mode):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from app.capabilities.router import router
    from app.config import Settings, get_settings
    from app.dependencies import get_agent_capabilities
    from app.stores.domain import UNSET
    captured = []
    class Capabilities:
        def __getattr__(self, name):
            def invoke(context, *args, **kwargs):
                captured.append((name, context, args, kwargs))
                return SimpleNamespace(to_dict=lambda: SUCCESS)
            return invoke
    backend = FastAPI()
    backend.include_router(router)
    backend.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_service_token="synthetic-internal-token", agent_environment="production")
    backend.dependency_overrides[get_agent_capabilities] = lambda: Capabilities()
    async def scenario():
        upstream = CapabilityHttpClient("http://internal", SecretStr("synthetic-internal-token"), environment="production", transport=httpx.ASGITransport(app=backend))
        tracer = Tracer()
        server = build_server(upstream, policy, tracer, principal=AgentPrincipal(actor_type="human_agent", actor_id="可信中文主体", environment="production"),
                              environment="production", inbound_token=TOKEN)
        async def elicit(_context, _params):
            return ElicitResult(action="accept", content={"confirmed": True})
        async with Client(server, mode=mode, elicitation_callback=elicit) as client:
            for name, arguments, _, _ in TOOL_CALLS:
                result = await client.call_tool(name, arguments)
                assert result.structured_content == {**SUCCESS, "error": None}, (name, result)
                target, context, args, kwargs = captured[-1]
                assert target == ("status" if name == "get_system_status" else name)
                assert context.actor_id == "可信中文主体" and context.environment == "production"
                assert context.approved is (name in {entry[0] for entry in WRITES})
                if name == "get_change_logs":
                    assert kwargs["actor"] == "business-filter"
                if name == "preview_store_changes":
                    assert args[0][0].notes is UNSET and args[0][0].store_code is UNSET
                if name == "apply_store_changes":
                    assert args[0][0].notes is None and args[0][0].store_code is UNSET
                    assert kwargs["expected_epoch"] == "epoch"
                if name == "get_operation":
                    assert kwargs == arguments
        assert len(captured) == len(TOOL_CALLS)
        assert len(tracer.records) == len(TOOL_CALLS)
        for record in tracer.records:
            assert set(record) <= {"tool_name", "actor_type", "actor_id", "environment", "run_id", "case_id", "operation_id", "timestamp", "code"}
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_page_schema_upper_bound_and_sync_enum_values(mode):
    async def scenario():
        requests = []
        async with Client(make_server(requests), mode=mode) as client:
            changes = [{"department_id": "d", "is_store": True}] * 500
            result = await client.call_tool("preview_store_changes", {"changes": changes, "expected_version": 0})
            assert result.structured_content["error"] is None
            for job_type in ("initialize", "reconcile", "full"):
                result = await client.call_tool("request_sync", {"job_type": job_type, "idempotency_key": job_type})
                assert result.structured_content["error"] is None
    asyncio.run(scenario())


@pytest.mark.parametrize("name,arguments,_method,_path", WRITES)
def test_modern_input_responses_without_server_state_cannot_authorize(name, arguments, _method, _path):
    from mcp.types import InputRequiredResult
    async def scenario():
        requests = []
        async def elicit(_context, _params):
            return ElicitResult(action="cancel")
        async with Client(make_server(requests, production=True), elicitation_callback=elicit) as client:
            pending = await client.session.call_tool(name, arguments, allow_input_required=True)
            answers = {key: ElicitResult(action="accept", content={"confirmed": True}) for key in pending.input_requests}
            result = await client.session.call_tool(name, arguments, input_responses=answers, allow_input_required=True)
            assert isinstance(result, InputRequiredResult)
            assert requests == []
    asyncio.run(scenario())

@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_configured_cli_runs_real_http_sdk_discovery(mode):
    from time import monotonic, sleep
    excluded = ("ORG_", "FEISHU_", "LARK_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "COZE_", "ARK_", "DASHSCOPE_")
    environment = {key: value for key, value in os.environ.items() if not key.startswith(excluded)}
    environment.update(ORG_MCP_SERVICE_TOKEN="synthetic-mcp-token", ORG_AGENT_SERVICE_TOKEN="synthetic-internal-token",
                       ORG_MCP_CAPABILITY_BASE_URL="http://127.0.0.1:1", ORG_AGENT_ENVIRONMENT="test",
                       ORG_MCP_ACTOR_TYPE="ci_agent", ORG_MCP_ACTOR_ID="cli-agent", ORG_MCP_RUN_ID="test-cli")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "app.mcp", "--port", str(port)],
                               cwd=Path(__file__).resolve().parents[1], env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    endpoint = f"http://127.0.0.1:{port}/mcp"
    try:
        deadline = monotonic() + 8
        with httpx.Client(trust_env=False, timeout=0.2) as probe:
            while True:
                assert process.poll() is None, "Configured CLI exited before readiness"
                try:
                    if probe.get(endpoint).status_code == 401:
                        break
                except httpx.TransportError:
                    pass
                assert monotonic() < deadline, "Configured CLI did not start"
                sleep(0.05)
        async def scenario():
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer synthetic-mcp-token"}, trust_env=False) as http:
                async with Client(streamable_http_client(endpoint, http_client=http), mode=mode) as client:
                    assert len((await client.list_tools()).tools) == 15
        asyncio.run(scenario())
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
