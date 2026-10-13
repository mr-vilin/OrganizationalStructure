import pytest
from app.capabilities.contracts import AgentContext, Observation, CapabilityResult
from app.capabilities.errors import OperationConflict

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
