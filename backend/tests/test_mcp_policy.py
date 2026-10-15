"""纯策略矩阵和只允许安全字段的递归脱敏追踪。"""
from datetime import datetime
import json
from types import MappingProxyType

import pytest
from pydantic import SecretStr

from app.mcp.models import AgentPrincipal
from app.mcp.policy import CapabilityLevel, PolicyDecision, TOOL_LEVELS, decide
from app.mcp.trace import Tracer, redact_trace


EXPECTED_LEVELS = {
    "get_system_status": "L0", "find_departments": "L0", "get_department": "L0",
    "list_employees": "L0", "get_employee": "L0", "list_stores": "L0",
    "get_store": "L0", "list_store_employees": "L0", "get_change_logs": "L0",
    "get_sync_job": "L0", "get_operation": "L0", "preview_store_changes": "L1",
    "apply_store_changes": "L2", "request_sync": "L2", "retry_sync_job": "L2",
}


def make_principal(actor_type="human_agent", environment="production"):
    return AgentPrincipal(actor_type=actor_type, actor_id="agent-1", environment=environment,
                          run_id="test-run" if environment == "test" else None, case_id="case-1")


def test_single_immutable_fifteen_tool_directory():
    assert dict(TOOL_LEVELS) == EXPECTED_LEVELS
    with pytest.raises(TypeError):
        TOOL_LEVELS["extra"] = CapabilityLevel.L3


@pytest.mark.parametrize("capability, level", list(EXPECTED_LEVELS.items()))
@pytest.mark.parametrize("actor_type, environment", [("human_agent", "production"), ("human_agent", "test"), ("ci_agent", "test")])
@pytest.mark.parametrize("approved", [False, True])
def test_policy_matrix(capability, level, actor_type, environment, approved):
    decision = decide(make_principal(actor_type, environment), capability, approved)
    assert isinstance(decision, PolicyDecision)
    requires = level == "L2" and environment == "production" and not approved
    assert decision.allowed is not requires
    assert decision.confirmation_required is requires
    assert decision.code == ("CONFIRMATION_REQUIRED" if requires else None)


@pytest.mark.parametrize("capability", list(EXPECTED_LEVELS))
def test_forged_production_ci_is_rejected_even_for_reads(capability):
    forged = AgentPrincipal.model_construct(actor_type="ci_agent", actor_id="agent-1", environment="production", run_id=None, case_id=None)
    assert decide(forged, capability, True).allowed is False


@pytest.mark.parametrize("identity", [("human_agent", "production"), ("human_agent", "test"), ("ci_agent", "test")])
def test_l3_and_unknown_are_denied_for_all_identities(identity, monkeypatch):
    principal = make_principal(*identity)
    assert decide(principal, "unknown", True).allowed is False
    monkeypatch.setattr("app.mcp.policy.TOOL_LEVELS", MappingProxyType({"restricted": CapabilityLevel.L3}))
    decision = decide(principal, "restricted", True)
    assert decision.allowed is False
    assert decision.confirmation_required is False


@pytest.mark.parametrize("approved", ["true", "false", {"approval_token": "anything"}, 1, None])
def test_only_strict_trusted_boolean_grants_confirmation(approved):
    assert not decide(make_principal(), "apply_store_changes", approved).allowed


def test_policy_defensively_rejects_unvalidated_principal():
    forged = AgentPrincipal.model_construct(actor_type="human_agent", actor_id="", environment="test", run_id="prod-run")
    assert not decide(forged, "get_operation", True).allowed


def test_recursive_redaction_is_case_insensitive_and_does_not_mutate():
    source = {"nested": [{"access_TOKEN": "synthetic-secret"}, {"Password": "synthetic-secret"}],
              "csrfValue": "synthetic-secret", "clientSecret": "synthetic-secret", "AUTHORIZATION": "Bearer synthetic-secret",
              "secret_object": SecretStr("synthetic-secret"), "safe": (SecretStr("synthetic-secret"), ValueError("synthetic-secret"))}
    redacted = redact_trace(source)
    assert redacted["nested"] == [{"access_TOKEN": "[REDACTED]"}, {"Password": "[REDACTED]"}]
    assert "synthetic-secret" not in repr(redacted) + json.dumps(redacted)
    assert source["nested"][0]["access_TOKEN"] == "synthetic-secret"


def test_redaction_handles_cycles_and_non_string_keys_without_repr():
    value = []
    value.append(value)
    assert redact_trace(value) == ["[REDACTED]"]
    assert redact_trace({ValueError("synthetic-secret"): "synthetic-secret"}) == {}


def test_tracer_records_only_allowlisted_metadata_with_utc_time(caplog):
    tracer = Tracer()
    result = tracer.record(tool_name="get_operation", principal=make_principal("ci_agent", "test"),
                           operation_id="op-1", code="OK", data={"employee": "synthetic-secret"},
                           authorization="Bearer synthetic-secret", exception=ValueError("synthetic-secret"))
    assert result == tracer.records[0]
    assert set(result) == {"tool_name", "actor_type", "actor_id", "environment", "run_id", "case_id", "operation_id", "timestamp", "code"}
    assert result["run_id"] == "test-run" and result["case_id"] == "case-1"
    assert datetime.fromisoformat(result["timestamp"]).utcoffset().total_seconds() == 0
    assert "synthetic-secret" not in repr(tracer.records) + caplog.text
    result["actor_id"] = "changed"
    assert tracer.records[0]["actor_id"] == "agent-1"


def test_tracer_drops_arbitrary_text_in_metadata():
    tracer = Tracer()
    result = tracer.record(tool_name="https://user:synthetic-secret@example.test", principal=make_principal(), operation_id="Bearer synthetic-secret", code="synthetic-secret")
    assert "synthetic-secret" not in repr(result)
    assert result["tool_name"] == "[REDACTED]"
    assert result["operation_id"] == "[REDACTED]"
    assert result["code"] == "[REDACTED]"



def test_incomplete_unvalidated_principal_is_denied_without_exception():
    principal = AgentPrincipal.model_construct(actor_id="agent-1")
    assert decide(principal, "get_operation", True).allowed is False


def test_trace_history_is_bounded():
    tracer = Tracer(max_records=1)
    tracer.record(tool_name="get_operation", principal=make_principal(), operation_id="op-1")
    tracer.record(tool_name="get_operation", principal=make_principal(), operation_id="op-2")
    assert len(tracer.records) == 1
    assert tracer.records[0]["operation_id"] == "op-2"


def test_trace_preserves_valid_unicode_identity_and_redacts_url_credentials():
    principal = AgentPrincipal(actor_type="human_agent", actor_id="配置主体一", environment="production", case_id="用例一")
    result = Tracer().record(tool_name="get_operation", principal=principal, operation_id="https://user:synthetic-secret@example.test")
    assert result["actor_id"] == "配置主体一"
    assert result["case_id"] == "用例一"
    assert result["operation_id"] == "[REDACTED]"
