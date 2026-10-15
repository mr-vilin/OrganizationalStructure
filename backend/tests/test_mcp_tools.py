"""内部能力 HTTP client 的 wire、身份和故障安全契约。"""
import asyncio
import base64
import json
import subprocess
import sys

import httpx
import pytest
from pydantic import SecretStr

from app.mcp.client import CapabilityHttpClient
from app.mcp.models import AgentPrincipal


BASE = "http://capabilities.internal"
TOKEN = SecretStr("synthetic-internal-token")
PRINCIPAL = AgentPrincipal(actor_type="human_agent", actor_id="agent-a", environment="production")
SUCCESS = {
    "operation_id": "op-1", "data": {"data": [{"id": "a", "name": "门店"}], "meta": {"data_version": 7}},
    "observation": {"execution_status": "succeeded", "fact_quality": "partial", "data_version": 7},
    "audit": {"actor_id": "agent-a"},
}
LEAK = "synthetic-private-value"


def encoded(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def run(coroutine):
    return asyncio.run(coroutine)


def client(handler, **kwargs):
    return CapabilityHttpClient(BASE, TOKEN, environment="production", transport=httpx.MockTransport(handler), **kwargs)


def test_read_preserves_four_fields_and_audit_actor_filter_is_not_identity():
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url == BASE + "/internal/capabilities/change-logs?actor=other&data_version=7"
        assert request.headers["Authorization"] == "Bearer synthetic-internal-token"
        assert request.headers["X-Agent-Actor-Type"] == "human_agent"
        assert request.headers["X-Agent-Actor-Id"] == encoded("agent-a")
        assert request.headers["X-Agent-Identity-Encoding"] == "base64url-utf8"
        assert request.headers["X-Agent-Environment"] == "production"
        assert request.headers["X-Agent-Approved"] == "false"
        assert "X-Agent-Run-Id" not in request.headers
        assert "X-Agent-Case-Id" not in request.headers
        return httpx.Response(200, json=SUCCESS)
    async def scenario():
        async with client(handle) as upstream:
            result = await upstream.read("/change-logs", {"actor": "other", "data_version": 7}, PRINCIPAL)
        assert result.model_dump() == {**SUCCESS, "error": None}
        assert len(requests) == 1
    run(scenario())


@pytest.mark.parametrize("approved,expected", [(False, "false"), (True, "true"), ("true", "false"), (1, "false")])
def test_call_trusted_approval_headers_and_explicit_null(approved, expected):
    payload = {"changes": [{"department_id": "a", "is_store": True, "notes": None}],
               "expected_epoch": "epoch", "expected_version": 7, "idempotency_key": "key",
               "actor_id": "forged", "approved": True, "environment": "test"}
    def handle(request):
        assert request.method == "POST"
        assert json.loads(request.content) == payload
        assert request.headers["X-Agent-Approved"] == expected
        assert request.headers["X-Agent-Actor-Id"] == encoded("agent-a")
        assert request.headers["X-Agent-Environment"] == "production"
        assert json.loads(request.content)["changes"][0]["notes"] is None
        assert "store_code" not in json.loads(request.content)["changes"][0]
        return httpx.Response(202, json={**SUCCESS, "data": {"status": "accepted", "job_id": "job-1"}})
    async def scenario():
        async with client(handle) as upstream:
            result = await upstream.call("/sync/jobs", payload, PRINCIPAL, approved=approved)
            assert result.data == {"status": "accepted", "job_id": "job-1"}
            assert result.observation == SUCCESS["observation"]
    run(scenario())


def test_test_environment_run_and_case_headers():
    principal = AgentPrincipal(actor_type="ci_agent", actor_id="ci-1", environment="test", run_id="test-run", case_id="case-1")
    def handle(request):
        assert request.headers["X-Agent-Run-Id"] == encoded("test-run")
        assert request.headers["X-Agent-Case-Id"] == encoded("case-1")
        assert request.headers["X-Agent-Environment"] == "test"
        return httpx.Response(200, json=SUCCESS)
    async def scenario():
        async with CapabilityHttpClient(BASE, TOKEN, environment="test", transport=httpx.MockTransport(handle)) as upstream:
            assert (await upstream.read("/status", {}, principal)).error is None
    run(scenario())


@pytest.mark.parametrize("principal", [
    AgentPrincipal(actor_type="human_agent", actor_id="agent-a", environment="test", run_id="test-run"),
    AgentPrincipal.model_construct(actor_type="ci_agent", actor_id="forged", environment="production"),
    AgentPrincipal.model_construct(actor_type="human_agent", actor_id={"secret": LEAK}, environment="production"),
])
def test_invalid_or_mismatched_principal_never_sends(principal, caplog, capsys):
    def handle(request):
        pytest.fail("invalid identity must not reach HTTP")
    async def scenario():
        async with client(handle) as upstream:
            result = await upstream.read("/status", {}, principal)
            assert result.error.code == "MCP_SERVICE_UNAUTHORIZED"
    run(scenario())
    assert LEAK not in caplog.text + capsys.readouterr().err


@pytest.mark.parametrize("status,code", [
    (401, "AGENT_SERVICE_UNAUTHORIZED"), (403, "CAPABILITY_NOT_ALLOWED"),
    (404, "OPERATION_NOT_FOUND"), (404, "DEPARTMENT_NOT_FOUND"),
    (409, "DATASET_CHANGED"), (409, "OPERATION_CONFLICT"), (409, "CONFIRMATION_REQUIRED"),
    (409, "JOB_NOT_RETRYABLE"), (400, "INVALID_CURSOR"),
    (422, "INVALID_CAPABILITY_REQUEST"), (422, "INVALID_JOB_SCOPE"), (422, "VALIDATION_ERROR"),
    (503, "DATABASE_NOT_CONFIGURED"), (503, "DATABASE_UNAVAILABLE"), (500, "DATABASE_ERROR"),
    (503, "INITIALIZATION_INCOMPLETE"), (503, "CAPABILITY_UNAVAILABLE"),
])
def test_known_error_codes_use_fixed_safe_message_and_discard_error_body(status, code):
    body = {"operation_id": LEAK, "data": {"employee": LEAK}, "audit": {"secret": LEAK},
            "error": {"code": code, "message": f"SQL SELECT {LEAK} https://user:{LEAK}@host/db", "debug": LEAK,
                      "fields": [{"loc": ["body", "changes", 0, "is_store"], "type": "bool_type", "msg": LEAK, "input": LEAK},
                                 {"loc": ["query", LEAK], "msg": LEAK}, {"field": "password", "value": LEAK}]}}
    async def scenario():
        async with client(lambda request: httpx.Response(status, json=body)) as upstream:
            result = await upstream.call("/sync/jobs", {}, PRINCIPAL)
            assert result.error.code == code
            assert result.error.retryable is False
            assert result.error.confirmation_required is (code == "CONFIRMATION_REQUIRED")
            assert result.error.fields == [{"field": "changes.0.is_store"}]
            assert result.operation_id is None and result.data is None and result.observation == {} and result.audit == {}
            assert LEAK not in result.model_dump_json()
    run(scenario())


@pytest.mark.parametrize("retryable,expected", [(True, True), (False, False), (None, False), ("true", False), (1, False)])
def test_5xx_retryable_only_if_explicit_true_and_never_retried(retryable, expected):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"code": "CAPABILITY_UNAVAILABLE", "message": LEAK, "retryable": retryable}})
    async def scenario():
        async with client(handle) as upstream:
            result = await upstream.call("/sync/jobs", {"idempotency_key": "same-key"}, PRINCIPAL)
            assert result.error.retryable is expected
            assert len(requests) == 1
    run(scenario())


def test_ambiguous_target_retains_only_safe_candidates_in_fields():
    candidate = {"id": "a", "name": "门店", "path": ["组织", "门店"], "status": "active"}
    body = {"error": {"code": "AMBIGUOUS_TARGET", "message": LEAK,
                      "candidates": [{**candidate, "token": LEAK, "employee": LEAK},
                                     {"id": "b", "name": f"Bearer {LEAK}", "path": [], "status": "active"}]}}
    async def scenario():
        async with client(lambda request: httpx.Response(409, json=body)) as upstream:
            result = await upstream.read("/departments", {"name": "门店"}, PRINCIPAL)
            assert result.error.code == "AMBIGUOUS_TARGET"
            assert result.error.fields[0]["candidates"][0] == candidate
            assert result.error.fields[0]["candidates"][1]["name"] == "[REDACTED]"
            assert LEAK not in result.model_dump_json()
    run(scenario())


@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_write_timeout_is_unconfirmed_and_suggests_get_operation_without_retry(exception, caplog):
    requests = []
    def handle(request):
        requests.append(request)
        raise exception(f"SQL {LEAK} https://user:{LEAK}@host/db", request=request)
    async def scenario():
        async with client(handle) as upstream:
            result = await upstream.call("/sync/jobs", {"idempotency_key": "same-key"}, PRINCIPAL)
            assert result.error.code == "UPSTREAM_TIMEOUT" and result.error.retryable is False
            assert result.observation["execution_status"] == "unconfirmed"
            assert "get_operation" in result.error.message
            assert result.data is None and result.operation_id is None
            assert LEAK not in result.model_dump_json()
            assert len(requests) == 1
    run(scenario())
    assert LEAK not in caplog.text


def test_network_failure_is_safe_and_does_not_retry():
    requests = []
    def handle(request):
        requests.append(request)
        raise httpx.ConnectError(f"Bearer {LEAK}", request=request)
    async def scenario():
        async with client(handle) as upstream:
            result = await upstream.read("/status", {}, PRINCIPAL)
            assert result.error.code == "UPSTREAM_UNAVAILABLE"
            assert result.error.retryable is False
            assert LEAK not in result.model_dump_json()
            assert len(requests) == 1
    run(scenario())


@pytest.mark.parametrize("status,body,expected", [
    (500, {"error": {"code": LEAK, "message": LEAK, "retryable": True}}, "UPSTREAM_UNAVAILABLE"),
    (400, {"error": {"code": LEAK, "message": LEAK}}, "UPSTREAM_INVALID_RESPONSE"),
    (200, {"data": LEAK}, "UPSTREAM_INVALID_RESPONSE"),
    (200, {**SUCCESS, "audit": []}, "UPSTREAM_INVALID_RESPONSE"),
    (200, {**SUCCESS, "operation_id": 1}, "UPSTREAM_INVALID_RESPONSE"),
    (200, {**SUCCESS, "error": {"code": LEAK}}, "UPSTREAM_INVALID_RESPONSE"),
    (500, [], "UPSTREAM_INVALID_RESPONSE"),
])
def test_invalid_envelopes_and_unknown_codes_never_echo_response(status, body, expected):
    async def scenario():
        async with client(lambda request: httpx.Response(status, json=body)) as upstream:
            result = await upstream.read("/status", {}, PRINCIPAL)
            assert result.error.code == expected
            assert result.error.retryable is False
            assert LEAK not in result.model_dump_json()
    run(scenario())


def test_non_json_response_and_success_secrets_are_filtered():
    async def scenario():
        async with client(lambda request: httpx.Response(502, text=f"SQL {LEAK}")) as upstream:
            assert (await upstream.read("/status", {}, PRINCIPAL)).error.code == "UPSTREAM_INVALID_RESPONSE"
        body = {**SUCCESS, "data": {"data": {"name": "员工", "token": LEAK, "oauth": {"raw": LEAK},
                                                "source": f"https://user:{LEAK}@host"}, "meta": {}}, "extra": LEAK}
        async with client(lambda request: httpx.Response(200, json=body)) as upstream:
            result = await upstream.read("/employees/a", {}, PRINCIPAL)
            assert result.data["data"]["name"] == "员工"
            assert LEAK not in result.model_dump_json()
    run(scenario())


def test_read_timeout_has_no_claim_about_execution_and_missing_retryable_is_false():
    def timeout(request):
        raise httpx.ReadTimeout(LEAK, request=request)
    async def scenario():
        async with client(timeout) as upstream:
            result = await upstream.read("/status", {}, PRINCIPAL)
            assert result.error.code == "UPSTREAM_TIMEOUT"
            assert result.observation == {} and result.error.retryable is False
        async with client(lambda request: httpx.Response(503, json={"error": {"code": "CAPABILITY_UNAVAILABLE"}})) as upstream:
            result = await upstream.call("/sync/jobs", None, PRINCIPAL)
            assert result.error.retryable is False
    run(scenario())


@pytest.mark.parametrize("path", ["https://other.invalid/steal", "//other.invalid/steal", "/../admin", "/%2e%2e/admin",
                                  "/status?x=1", "/status#fragment", "/status\\..\\admin", "status", "/%252e%252e/admin"])
def test_non_fixed_internal_paths_cannot_send_credentials(path):
    async def scenario():
        async with client(lambda request: pytest.fail("invalid path must not send")) as upstream:
            assert (await upstream.read(path, {}, PRINCIPAL)).error.code == "CAPABILITY_FORBIDDEN"
    run(scenario())


def test_injected_client_cannot_override_identity_auth_or_redirect_and_timeout_is_explicit():
    requests = []
    def handle(request):
        requests.append(request)
        assert request.url == BASE + "/internal/capabilities/status"
        assert request.headers["Authorization"] == "Bearer synthetic-internal-token"
        assert request.headers["X-Agent-Actor-Id"] == encoded("agent-a")
        assert "cookie" not in request.headers
        assert request.extensions["timeout"] == {"connect": 1, "read": 2, "write": 2, "pool": 1}
        return httpx.Response(307, headers={"location": f"https://other.invalid/{LEAK}"})
    async def scenario():
        injected = httpx.AsyncClient(base_url="https://other.invalid", auth=("forged", LEAK),
                                    headers={"Authorization": f"Bearer {LEAK}", "X-Agent-Actor-Id": "forged"},
                                    cookies={"secret": LEAK}, params={"token": LEAK}, follow_redirects=True,
                                    transport=httpx.MockTransport(handle))
        upstream = CapabilityHttpClient(BASE, TOKEN, environment="production", client=injected, connect_timeout=1, read_timeout=2)
        async with upstream:
            result = await upstream.read("/status", {}, PRINCIPAL)
            assert result.error.code == "UPSTREAM_INVALID_RESPONSE"
            assert LEAK not in result.model_dump_json()
        assert injected.is_closed  # 注入即转移生命周期；关闭幂等。
        await upstream.aclose()
        assert len(requests) == 1
    run(scenario())


@pytest.mark.parametrize("base", ["ftp://host", "http://user:pass@host", "http://host?token=x", "http://host#part", "http://host/admin"])
def test_invalid_configuration_fails_without_echoing_values(base):
    with pytest.raises(ValueError) as captured:
        CapabilityHttpClient(base, TOKEN, environment="production")
    assert base not in str(captured.value)


@pytest.mark.parametrize("updates", [
    {"service_token": SecretStr("")}, {"service_token": SecretStr(" ")},
    {"service_token": SecretStr("bad\nheader")}, {"service_token": SecretStr("中文")},
    {"environment": "staging"}, {"connect_timeout": 0}, {"read_timeout": float("inf")},
    {"connect_timeout": True}, {"read_timeout": -1},
])
def test_invalid_token_environment_or_timeout_configuration_is_fixed_safe_failure(updates):
    options = {"service_token": TOKEN, "environment": "production", **updates}
    with pytest.raises(ValueError, match="^Invalid capability HTTP client configuration.$"):
        CapabilityHttpClient(BASE, **options)


def test_base_with_internal_prefix_and_closed_client_are_supported():
    async def scenario():
        upstream = CapabilityHttpClient(BASE + "/internal/capabilities/", TOKEN, environment="production",
                                        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=SUCCESS)))
        assert (await upstream.read("/status", {}, PRINCIPAL)).error is None
        await upstream.aclose()
        result = await upstream.read("/status", {}, PRINCIPAL)
        assert result.error.code == "UPSTREAM_UNAVAILABLE"
    run(scenario())


def test_client_import_does_not_load_business_or_orm():
    result = subprocess.run([sys.executable, "-c", "import sys; import app.mcp.client; assert not any(n in sys.modules for n in ('app.capabilities', 'app.persistence', 'sqlalchemy', 'app.main'))"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("environment,actor_type,run_id", [
    ("production", "human_agent", "运行一"), ("test", "ci_agent", "test-运行一"),
])
def test_chinese_identity_round_trips_through_real_internal_asgi_dependency(environment, actor_type, run_id):
    from types import SimpleNamespace
    from app.config import Settings, get_settings
    from app.dependencies import get_runtime
    from app.main import app

    captured = []
    def status(context):
        captured.append(context)
        return SimpleNamespace(to_dict=lambda: {**SUCCESS, "audit": {"actor_id": context.actor_id, "run_id": context.run_id, "case_id": context.case_id}})
    principal = AgentPrincipal(actor_type=actor_type, actor_id="中文主体", environment=environment, run_id=run_id, case_id="中文用例")
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, agent_service_token=TOKEN, agent_environment=environment)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(capabilities=SimpleNamespace(status=status))
    async def scenario():
        async with CapabilityHttpClient(BASE, TOKEN, environment=environment, transport=httpx.ASGITransport(app=app)) as upstream:
            result = await upstream.read("/status", {}, principal)
            assert result.error is None
            assert result.audit == {"actor_id": "中文主体", "run_id": run_id, "case_id": "中文用例"}
            assert len(captured) == 1
            assert captured[0].actor_type == actor_type and captured[0].environment == environment
            assert captured[0].approved is False
    try:
        run(scenario())
    finally:
        app.dependency_overrides.clear()
