from datetime import datetime, timezone

from sqlalchemy.dialects import mysql

from app.main import app
from app.persistence.repositories import SqlIdentityRepository
from app.stores.domain import UNSET, StorePatch, merge_store_patch
from app.web import utc_datetime


def test_persistent_session_query_has_explicit_allowlist_join():
    statement = SqlIdentityRepository.session_auth_statement("sid", datetime(2026, 9, 15))
    sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "JOIN admin_allowlist ON admin_allowlist.open_id = admin_session.open_id" in sql


def test_store_patch_preserves_omitted_fields_and_null_can_clear_code():
    current = {"is_store": True, "store_code": "A-01", "notes": "历史备注"}
    toggled = merge_store_patch(current, StorePatch("DepA", False))
    cleared = merge_store_patch(current, StorePatch("DepA", True, store_code=None))
    notes_only = merge_store_patch(current, StorePatch("DepA", True, notes="新备注"))
    assert toggled == {"is_store": False, "store_code": "A-01", "notes": "历史备注"}
    assert cleared == {"is_store": True, "store_code": None, "notes": "历史备注"}
    assert notes_only == {"is_store": True, "store_code": "A-01", "notes": "新备注"}


def test_naive_database_datetime_is_serialized_as_utc():
    assert utc_datetime(datetime(2026, 9, 15, 3, 4, 5)).isoformat() == "2026-09-15T03:04:05+00:00"
    aware = datetime(2026, 9, 15, 3, 4, 5, tzinfo=timezone.utc)
    assert utc_datetime(aware) is aware


def test_store_employee_endpoints_support_cross_endpoint_version_and_admin_alias():
    schema = app.openapi()["paths"]
    public_parameters = {item["name"] for item in schema["/api/v1/stores/{store_id}/employees"]["get"]["parameters"]}
    assert {"dataset_epoch", "data_version"} <= public_parameters
    assert "/admin/api/stores/{store_id}/employees" in schema


def test_task_list_has_stable_cursor_parameter():
    parameters = {item["name"] for item in app.openapi()["paths"]["/admin/api/sync/jobs"]["get"]["parameters"]}
    assert "cursor" in parameters
