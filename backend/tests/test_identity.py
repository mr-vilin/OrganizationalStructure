from datetime import datetime, timedelta, timezone

from app.identity.services import ApiCredentialService, SessionService


NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


def test_session_requires_allowlisted_identity_and_valid_csrf_for_writes():
    sessions = SessionService(secret="s" * 32, allowlist={"ou_Admin"})
    issued = sessions.create("ou_Admin", NOW)

    identity = sessions.authenticate(issued.session_token, NOW + timedelta(minutes=1))

    assert identity.open_id == "ou_Admin"
    assert sessions.verify_csrf(identity, issued.csrf_token) is True
    assert sessions.verify_csrf(identity, "wrong") is False


def test_removing_allowlist_entry_immediately_revokes_session():
    sessions = SessionService(secret="s" * 32, allowlist={"ou_Admin"})
    issued = sessions.create("ou_Admin", NOW)
    sessions.set_allowlist(set())

    assert sessions.authenticate(issued.session_token, NOW) is None


def test_source_id_allowlist_is_case_sensitive():
    sessions = SessionService(secret="s" * 32, allowlist={"ou_Admin"})

    assert sessions.create("ou_admin", NOW) is None


def test_api_secret_is_hashed_returned_once_and_revocation_is_immediate():
    service = ApiCredentialService(pepper="p" * 32)
    issued = service.issue("Payroll", NOW)

    assert issued.secret not in service.export_records()[0].secret_hash
    assert service.authenticate(issued.client_id, issued.secret, NOW) is not None
    service.revoke(issued.client_id, NOW)
    assert service.authenticate(issued.client_id, issued.secret, NOW) is None

