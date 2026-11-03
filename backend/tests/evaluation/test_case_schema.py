from dataclasses import FrozenInstanceError, fields, replace
import json
from pathlib import Path

import pytest
import yaml

from app.evaluation.cases import load_case, load_cases, validate_case
from app.evaluation.models import (
    AgentRun, AgentRunContext, EvaluationCase, EvaluationReport, ToolTraceEvent,
)
from app.mcp.policy import TOOL_LEVELS


CASES = Path(__file__).parent / "cases"
PRIMARY = CASES / "ORG_AGENT_READ_PRIMARY_STORE.yaml"
NOT_IN_STORE = CASES / "ORG_AGENT_READ_NOT_IN_STORE.yaml"


def document():
    return {
        "schema_version": 1, "case_id": "ORG_AGENT_READ_TEST", "goal": "读取合成员工归属。",
        "fixture": {}, "allowed_tools": ["get_employee"],
        "expected_state": {"primary_store_id": "store_people"}, "forbidden_effects": [],
        "timeout_seconds": 30, "max_tool_calls": 5,
    }


def write_case(tmp_path, data):
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_case_requires_goal_expected_state_and_forbidden_effects():
    case = load_case(PRIMARY)
    assert case.case_id == "ORG_AGENT_READ_PRIMARY_STORE"
    assert case.goal and case.allowed_tools
    assert case.expected_state["primary_store_id"] == "store_people"
    assert case.timeout_seconds > 0
    assert isinstance(case, EvaluationCase)
    assert isinstance(case.allowed_tools, tuple)
    assert isinstance(case.forbidden_effects, tuple)
    assert validate_case(case) == case


@pytest.mark.parametrize("field", tuple(document()))
def test_every_document_field_is_required(tmp_path, field):
    data = document()
    del data[field]
    with pytest.raises(ValueError):
        load_case(write_case(tmp_path, data))


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("schema_version", "1"), ("schema_version", True),
    ("case_id", ""), ("case_id", "   "), ("case_id", "bad id"), ("case_id", 123),
    ("goal", ""), ("goal", " \n\t"), ("goal", 123),
    ("allowed_tools", []), ("allowed_tools", ["unknown_tool"]),
    ("allowed_tools", ["get_employee", "get_employee"]), ("allowed_tools", "get_employee"),
    ("expected_state", {}), ("expected_state", []), ("expected_state", None),
    ("fixture", []), ("fixture", None),
    ("forbidden_effects", {}), ("forbidden_effects", ["写操作"]),
    ("forbidden_effects", [{}]), ("timeout_seconds", 0), ("timeout_seconds", -1),
    ("timeout_seconds", True), ("timeout_seconds", "30"),
    ("max_tool_calls", 0), ("max_tool_calls", -1), ("max_tool_calls", 1.5),
])
def test_invalid_case_fields_are_rejected(tmp_path, field, value):
    data = {**document(), field: value}
    with pytest.raises(ValueError):
        load_case(write_case(tmp_path, data))


def test_unknown_document_fields_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_case(write_case(tmp_path, {**document(), "unexpected": True}))


@pytest.mark.parametrize("source", [
    "", "[]", "null", "case_id: [", "!!python/object/apply:builtins.str ['unsafe']",
    "schema_version: 1\nschema_version: 2\n", "1: value\n",
])
def test_unsafe_malformed_or_ambiguous_yaml_is_rejected(tmp_path, source):
    path = tmp_path / "invalid.yaml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError):
        load_case(path)


def test_all_authoritative_tools_can_be_validated(tmp_path):
    assert len(TOOL_LEVELS) == 15
    data = {**document(), "allowed_tools": list(TOOL_LEVELS)}
    assert set(load_case(write_case(tmp_path, data)).allowed_tools) == set(TOOL_LEVELS)


def test_validate_case_rejects_invalid_direct_dataclass():
    case = load_case(PRIMARY)
    for changes in ({"goal": " "}, {"timeout_seconds": -1}, {"allowed_tools": ("not_a_tool",)}):
        with pytest.raises(ValueError):
            validate_case(replace(case, **changes))


def test_suite_rejects_duplicate_ids_but_loading_has_no_global_state(tmp_path):
    assert load_case(PRIMARY) == load_case(PRIMARY)
    assert len(load_cases([PRIMARY, NOT_IN_STORE])) == 2
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_cases([PRIMARY, PRIMARY])
    copied = tmp_path / "copied.yaml"
    copied.write_text(PRIMARY.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_cases([PRIMARY, copied])
    assert len(load_cases([PRIMARY, NOT_IN_STORE])) == 2


@pytest.mark.parametrize("path,primary_department,primary_store,status,stores", [
    (PRIMARY, "people_service", "store_people", "resolved", {"store_people", "store_river"}),
    (NOT_IN_STORE, "hq", None, "not_in_store", {"store_people"}),
])
def test_read_fixtures_have_explicit_seed_rows_and_literal_expectations(
    path, primary_department, primary_store, status, stores,
):
    case = load_case(path)
    fixture = case.fixture
    departments = {row["id"] for row in fixture["departments"]}
    employee, = fixture["employees"]
    assert employee["primary_department_id"] == primary_department
    assert employee["primary_store_status"] == status
    memberships = fixture["employee_departments"]
    assert memberships[0]["is_primary"] is False
    primary, = [row for row in memberships if row["is_primary"]]
    assert primary["department_id"] == primary_department
    assert all(row["department_id"] in departments and row["employee_id"] == employee["id"] for row in memberships)
    assert {row["store_id"] for row in fixture["employee_stores"]} == stores
    assert all(row["store_id"] in departments and row["path"][-1] == row["store_id"] for row in fixture["employee_stores"])
    assert {row["department_id"] for row in fixture["store_profiles"]} <= departments
    assert case.expected_state == {
        "employee_id": employee["id"], "primary_department_id": primary_department,
        "primary_store_id": primary_store, "primary_store_status": status,
        "store_ids": sorted(stores),
        "read_completion": {"predicate": "employee_attribution"},
    }
    assert {tool for tool in case.allowed_tools} <= {"get_employee", "get_department", "list_stores", "get_store", "list_store_employees"}
    assert case.forbidden_effects == (
        {"predicate": "business_tables_unchanged"},
        {"predicate": "data_version_unchanged"},
        {"predicate": "no_new_operation_receipts"},
        {"predicate": "no_new_sync_jobs"},
        {"predicate": "no_new_change_logs"},
        {"predicate": "no_feishu_writes"},
    )
    assert fixture["dataset_state"]["initialization_status"] == "complete"
    assert fixture["fake_feishu"]["scenario_id"] == case.case_id
    schedule, = fixture["system_settings"]
    assert schedule["key"] == "reconcile_schedule"
    assert json.loads(schedule["value"]) == {
        "enabled": False, "local_time": "03:00", "timezone": "Asia/Shanghai", "updated_at": None,
    }


@pytest.mark.parametrize("path", [PRIMARY, NOT_IN_STORE])
def test_fixtures_match_seed_model_columns_and_foreign_keys_without_database(path):
    from app.persistence.models import (
        DatasetState, Department, Employee, EmployeeDepartment, EmployeeStore, StoreProfile, SystemSetting,
    )

    fixture = load_case(path).fixture
    for key, model in (
        ("dataset_state", DatasetState), ("departments", Department), ("employees", Employee),
        ("employee_departments", EmployeeDepartment), ("employee_stores", EmployeeStore),
        ("store_profiles", StoreProfile), ("system_settings", SystemSetting),
    ):
        rows = [fixture[key]] if key == "dataset_state" else fixture[key]
        columns = {column.name for column in model.__table__.columns}
        required = {
            column.name for column in model.__table__.columns
            if not column.nullable and column.default is None and column.server_default is None
        }
        for row in rows:
            assert set(row) <= columns
            assert required <= set(row)
            model(**row)  # 仅构造 ORM 行，不创建 engine 或 Session。
    seen = set()
    for department in fixture["departments"]:
        assert department["parent_id"] is None or department["parent_id"] in seen
        seen.add(department["id"])
    employee, = fixture["employees"]
    assert employee["primary_department_id"] in seen
    primary_stores = [row["store_id"] for row in fixture["employee_stores"] if row["is_primary"]]
    expected = load_case(path).expected_state["primary_store_id"]
    assert primary_stores == ([] if expected is None else [expected])


def test_fixed_models_have_exact_fields_and_are_frozen():
    expected = {
        EvaluationCase: "case_id goal fixture allowed_tools expected_state forbidden_effects timeout_seconds max_tool_calls",
        ToolTraceEvent: "sequence tool_name arguments result_code operation_id started_at finished_at",
        AgentRunContext: "run_id case_id actor_id environment",
        AgentRun: "final_text trace terminal_observation",
        EvaluationReport: "case_id run_id hard_passed hard_failures soft_scores evidence trace",
    }
    for model, names in expected.items():
        assert [field.name for field in fields(model)] == names.split()
        assert model.__dataclass_params__.frozen
    context = AgentRunContext("test-run", "case", "ci", "test")
    with pytest.raises(FrozenInstanceError):
        context.actor_id = "other"
