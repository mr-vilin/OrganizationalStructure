import pytest
from datetime import datetime
from app.capabilities.contracts import AgentContext, Observation, CapabilityResult
from app.capabilities.errors import (OperationConflict, ConfirmationRequired, OperationNotFound, CapabilityNotAllowed, InvalidCapabilityRequest, DatasetChangedError, CapabilityUnavailable)

def observation(**kwargs):
    values = dict(execution="verified", fact_quality="resolved", dataset_epoch="e", data_version=1, next_action=None, evidence={})
    values.update(kwargs)
    return Observation(**values)

def test_store_apply_result_contains_operation_and_observation():
    result = CapabilityResult("op_1", {"changed_count": 1}, observation(execution="submitted", data_version=43, evidence={"change_log_ids": ["log_1"]}), {"actor_id": "agent_1"})
    assert result.to_dict()["observation"]["data_version"] == 43

def test_unknown_state_rejected():
    with pytest.raises(ValueError): observation(execution="bogus")

def test_illegal_environment_rejected():
    with pytest.raises(ValueError): AgentContext("human_agent", "a", "sandbox")

def test_write_result_requires_operation_id():
    with pytest.raises(ValueError): CapabilityResult(None, {}, observation(execution="submitted"), {})

def test_error_serialization_is_stable():
    error = OperationConflict()
    assert error.status == 409
    assert error.to_dict() == {"error": {"code": "OPERATION_CONFLICT", "message": "Operation conflicts with current state"}}

def test_nested_inputs_are_frozen_and_json_serialized():
    evidence = {"ids": ["a"], "when": datetime(2026, 1, 2)}
    data = {"items": [{"x": 1}]}
    audit = {"tags": {"safe"}}
    result = CapabilityResult("op", data, observation(evidence=evidence), audit)
    evidence["ids"].append("b"); data["items"][0]["x"] = 9; audit["tags"].add("changed")
    assert result.to_dict()["data"] == {"items": [{"x": 1}]}
    assert result.to_dict()["observation"]["evidence"]["ids"] == ["a"]
    assert result.to_dict()["audit"]["tags"] == ["safe"]
    assert result.to_dict()["observation"]["evidence"]["when"] == "2026-01-02T00:00:00"

def test_non_json_custom_value_fails_deterministically():
    with pytest.raises(TypeError, match="not JSON encodable"):
        CapabilityResult("op", object(), observation(), {}).to_dict()

@pytest.mark.parametrize("error_type", [OperationConflict, ConfirmationRequired, OperationNotFound, CapabilityNotAllowed, InvalidCapabilityRequest, DatasetChangedError, CapabilityUnavailable])
def test_error_ignores_sensitive_caller_message(error_type):
    assert "secret" not in error_type("secret-token").to_dict()["error"]["message"]


def test_explicit_read_classification_preserves_four_field_wire_and_write_default_guard():
    result = CapabilityResult(None, {}, observation(execution="submitted"), {}, write_operation=False)
    assert set(result.to_dict()) == {"operation_id", "data", "observation", "audit"}
    assert result.operation_id is None
    with pytest.raises(ValueError): CapabilityResult(None, {}, observation(execution="submitted"), {})


def test_set_serialization_is_stable():
    result = CapabilityResult("op", {"values":{"z", "a", "m"}}, observation(), {})
    assert result.to_dict()["data"]["values"] == ["a", "m", "z"]
