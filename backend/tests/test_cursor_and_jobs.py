from datetime import datetime, timezone

import pytest

from app.public_api.cursor import CursorCodec, DatasetChanged, InvalidCursor
from app.sync.services import JobService


def test_cursor_binds_filters_epoch_version_and_last_id():
    codec = CursorCodec("c" * 32)
    cursor = codec.encode(epoch="EpochA", version=8, filters={"status": "active"}, last_id="DepZ")

    page = codec.decode(cursor, epoch="EpochA", version=8, filters={"status": "active"})

    assert page.last_id == "DepZ"
    with pytest.raises(DatasetChanged):
        codec.decode(cursor, epoch="EpochA", version=9, filters={"status": "active"})
    with pytest.raises(InvalidCursor):
        codec.decode(cursor, epoch="EpochA", version=8, filters={"status": "inactive"})


def test_running_job_with_same_scope_is_reused_and_failed_job_can_retry():
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    service = JobService()
    first = service.submit("subtree", "DepA", "admin:ou1", now)
    duplicate = service.submit("subtree", "DepA", "admin:ou1", now)

    assert duplicate.job_id == first.job_id
    assert duplicate.reused is True
    service.fail(first.job_id, "REMOTE_TIMEOUT", now)
    retried = service.retry(first.job_id, "admin:ou1", now)
    assert retried.attempt == 2
    assert retried.status == "queued"

