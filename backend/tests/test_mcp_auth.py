"""独立 MCP 身份和 wire 模型安全边界。"""
import subprocess
import sys

import pytest
from pydantic import SecretStr, ValidationError

from app.mcp.auth import AuthenticationError, authenticate, validate_principal, verify_service_token
from app.mcp.models import AgentPrincipal, ToolError, ToolResult


def principal(**updates):
    return {"actor_type": "human_agent", "actor_id": "agent-1", "environment": "production", **updates}


@pytest.mark.parametrize("value, expected, accepted", [
    ("synthetic-mcp-token", "synthetic-mcp-token", True),
    ("synthetic-backend-token", "synthetic-mcp-token", False),
    ("", "", False), (" ", " ", False), ("x", "", False),
    ("", "x", False), ("é", "é", True), ("x", "y", False),
])
def test_token_is_exact_constant_time_and_disabled_when_empty(value, expected, accepted):
    assert verify_service_token(value, SecretStr(expected)) is accepted


def test_token_uses_compare_digest(monkeypatch):
    calls = []
    monkeypatch.setattr("app.mcp.auth.hmac.compare_digest", lambda left, right: calls.append((left, right)) or True)
    assert verify_service_token("synthetic-mcp-token", SecretStr("synthetic-mcp-token"))
    assert calls == [(b"synthetic-mcp-token", b"synthetic-mcp-token")]


@pytest.mark.parametrize("authorization", [None, "", "Bearer", "Basic synthetic-secret", "Bearer  synthetic-secret", "Bearer synthetic-secret\n", "Bearer synthetic-backend-token"])
def test_bad_authentication_has_safe_fixed_failure(authorization, caplog):
    with pytest.raises(AuthenticationError) as captured:
        authenticate(authorization, expected_token=SecretStr("synthetic-mcp-token"), principal=principal(), environment="production")
    assert captured.value.code == "MCP_SERVICE_UNAUTHORIZED"
    assert "synthetic" not in str(captured.value) + repr(captured.value) + caplog.text


def test_authentication_binds_trusted_principal_and_ignores_no_headers():
    trusted = validate_principal(principal(), environment="production")
    authenticated = authenticate("Bearer synthetic-mcp-token", expected_token=SecretStr("synthetic-mcp-token"), principal=trusted, environment="production")
    assert authenticated == trusted
    assert "token" not in authenticated.model_dump()
    with pytest.raises(ValidationError):
        authenticated.actor_id = "forged"


@pytest.mark.parametrize("updates", [
    {"actor_id": ""}, {"actor_id": " "}, {"actor_id": "two words"},
    {"actor_id": "a\x00b"}, {"actor_id": "a" * 192}, {"actor_id": 123},
    {"run_id": ""}, {"case_id": "bad\ncase"}, {"case_id": "a" * 192},
    {"environment": "staging"}, {"environment": "test", "run_id": "test-run"},
    {"run_id": "test-run"}, {"run_id": "test_run"},
    {"actor_type": "ci_agent"}, {"actor_type": "ci_agent", "run_id": "prod-run"},
    {"actor_type": "admin"}, {"approved": True}, {"approval_token": "synthetic-secret"},
])
def test_invalid_principal_fails_closed(updates):
    with pytest.raises(AuthenticationError) as captured:
        validate_principal(principal(**updates), environment="production")
    assert "synthetic" not in repr(captured.value)
    assert str(captured.value) == "MCP service authentication failed."


@pytest.mark.parametrize("actor_type", ["human_agent", "ci_agent"])
@pytest.mark.parametrize("run_id, accepted", [(None, False), ("run", False), ("test-", True), ("test_", True), ("test-run", True), ("test_run", True)])
def test_test_identity_requires_safe_run(actor_type, run_id, accepted):
    value = principal(actor_type=actor_type, environment="test", run_id=run_id, case_id="case-1")
    if accepted:
        assert validate_principal(value, environment="test").case_id == "case-1"
    else:
        with pytest.raises(AuthenticationError):
            validate_principal(value, environment="test")


def test_models_preserve_wire_result_and_safe_error_factory():
    result = ToolResult(operation_id="op-1", data={"data": [], "meta": {"data_version": 2}}, observation={"execution": "submitted"}, audit={"actor_id": "agent-1"})
    assert set(result.model_dump()) == {"operation_id", "data", "observation", "audit", "error"}
    assert result.data["meta"]["data_version"] == 2
    error = ToolResult.failure("CONFIRMATION_REQUIRED", field_names=["expected_epoch"])
    assert isinstance(error.error, ToolError)
    assert error.error.confirmation_required is True
    assert error.error.retryable is False
    assert error.error.fields == [{"field": "expected_epoch"}]
    unsafe = ToolResult.failure("synthetic-secret", field_names=["password=synthetic-secret"])
    assert unsafe.error.code == "MCP_INTERNAL_ERROR"
    assert "synthetic-secret" not in repr(unsafe) + unsafe.model_dump_json()


@pytest.mark.parametrize("supplied, configured", [("\ud800", "safe"), ("safe", "\ud800")])
def test_invalid_unicode_token_is_a_safe_denial(supplied, configured):
    assert verify_service_token(supplied, SecretStr(configured)) is False


def test_principal_validation_error_string_and_repr_hide_input():
    with pytest.raises(ValidationError) as captured:
        AgentPrincipal(**principal(actor_id="synthetic-secret " * 20))
    assert "synthetic-secret" not in str(captured.value) + repr(captured.value)



def test_new_components_do_not_import_business_or_database_modules():
    script = """
import sys
from app.mcp import models, auth, policy, trace
for prefix in ('app.capabilities', 'app.persistence', 'sqlalchemy', 'app.main'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entry", ["validate", "decide", "trace"])
@pytest.mark.parametrize("construction", ["construct", "copy"])
@pytest.mark.parametrize("field, bad_kind", [
    ("actor_id", "dict"), ("actor_id", "list"), ("actor_id", "exception"),
    ("actor_id", "secret"), ("actor_type", "dict"), ("environment", "dict"),
    ("run_id", "dict"), ("case_id", "dict"),
])
@pytest.mark.parametrize("warning_channel", ["record", "stderr"])
def test_invalid_constructed_principal_never_leaks_diagnostics(
    entry, construction, field, bad_kind, warning_channel, capfd, caplog,
):
    import warnings

    from app.mcp.policy import decide
    from app.mcp.trace import Tracer

    caplog.set_level("DEBUG")
    marker = "synthetic-review-secret"
    bad_value = {
        "dict": {"password": marker}, "list": [marker],
        "exception": ValueError(marker), "secret": SecretStr(marker),
    }[bad_kind]
    if construction == "construct":
        forged = AgentPrincipal.model_construct(**principal(**{field: bad_value}))
    else:
        forged = AgentPrincipal(**principal()).model_copy(update={field: bad_value})
    tracer = Tracer()
    captured_error = None
    with warnings.catch_warnings(record=warning_channel == "record") as diagnostic_warnings:
        warnings.simplefilter("always")
        if warning_channel == "stderr":
            # 直接使用标准格式写 stderr，避免 pytest 自身的 warning 收集器代收。
            def emit_warning(message, category, filename, lineno, file=None, line=None):
                (file or sys.stderr).write(warnings.formatwarning(message, category, filename, lineno, line))
            warnings.showwarning = emit_warning
        if entry == "decide":
            result = decide(forged, "get_operation", False)
            assert result.allowed is False
            assert result.code == "CAPABILITY_FORBIDDEN"
        else:
            with pytest.raises(AuthenticationError) as captured:
                if entry == "validate":
                    validate_principal(forged, environment="production")
                else:
                    tracer.record(tool_name="get_operation", principal=forged)
            captured_error = captured.value
    streams = capfd.readouterr()
    warning_text = "".join(str(item.message) for item in diagnostic_warnings or [])
    rendered_error = "" if captured_error is None else str(captured_error) + repr(captured_error)
    assert marker not in warning_text + streams.out + streams.err + caplog.text + rendered_error
    assert not diagnostic_warnings
    assert streams.err == ""
    assert tracer.records == ()



@pytest.mark.parametrize("entry", ["validate", "decide", "trace"])
def test_copied_principal_extra_sensitive_value_is_rejected_without_serialization(entry, capfd, caplog):
    import warnings

    from app.mcp.policy import decide
    from app.mcp.trace import Tracer

    caplog.set_level("DEBUG")
    marker = "synthetic-review-secret"
    forged = AgentPrincipal(**principal()).model_copy(update={"password": marker})
    tracer = Tracer()
    rendered_error = ""
    with warnings.catch_warnings(record=True) as diagnostic_warnings:
        warnings.simplefilter("always")
        if entry == "decide":
            assert decide(forged, "get_operation", False).allowed is False
        else:
            with pytest.raises(AuthenticationError) as captured:
                if entry == "validate":
                    validate_principal(forged, environment="production")
                else:
                    tracer.record(tool_name="get_operation", principal=forged)
            rendered_error = str(captured.value) + repr(captured.value)
    streams = capfd.readouterr()
    assert not diagnostic_warnings
    assert streams.err == ""
    assert marker not in streams.out + streams.err + caplog.text + rendered_error
    assert tracer.records == ()
