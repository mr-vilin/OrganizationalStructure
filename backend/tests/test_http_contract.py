from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_liveness_works_without_production_configuration_and_readiness_is_explicit():
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "DATABASE_NOT_CONFIGURED"


def test_anonymous_public_request_is_401_with_error_envelope():
    response = client.get("/api/v1/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_machine_credential_cannot_use_admin_write_endpoint():
    response = client.post(
        "/admin/api/sync/jobs",
        headers={"Authorization": "Bearer client.secret"},
        json={"type": "full"},
    )
    assert response.status_code == 401


def test_initialized_status_uses_data_meta_envelope_with_dependency_replacement():
    from app.dependencies import get_public_identity, get_read_service

    class FakeReadService:
        def status(self):
            return ({"initialization_status": "complete"}, {"dataset_epoch": "EpochA", "data_version": 7})

    app.dependency_overrides[get_public_identity] = lambda: {"client_id": "ClientA"}
    app.dependency_overrides[get_read_service] = FakeReadService
    try:
        response = client.get("/api/v1/status")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "data": {"initialization_status": "complete"},
        "meta": {"dataset_epoch": "EpochA", "data_version": 7},
    }


def test_management_contract_registers_store_audit_allowlist_and_client_routes():
    paths = app.openapi()["paths"]
    expected = {
        "/admin/api/stores/batch/preview",
        "/admin/api/stores/batch/apply",
        "/admin/api/stores/{store_id}",
        "/admin/api/change-logs",
        "/admin/api/admin-allowlist",
        "/admin/api/admin-allowlist/{open_id}",
        "/admin/api/api-clients",
        "/admin/api/api-clients/{client_id}/rotate",
        "/admin/api/api-clients/{client_id}/revoke",
    }
    assert expected <= set(paths)
