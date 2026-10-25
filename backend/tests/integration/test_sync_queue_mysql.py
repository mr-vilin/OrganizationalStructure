"""真实 MySQL 8.4 队列排序、门禁与空闲返回验收。"""
import pytest

from test_sync_queue_order import (
    assert_initialization_backoff_is_respected,
    assert_initialization_is_not_starved,
    assert_pending_event_is_idle,
    assert_waiting_reconcile_is_idle,
)


@pytest.mark.parametrize("scenario", [
    assert_initialization_is_not_starved,
    assert_waiting_reconcile_is_idle,
    assert_initialization_backoff_is_respected,
    assert_pending_event_is_idle,
], ids=["initialization-first", "reconcile-idle", "retry-backoff", "event-idle"])
def test_initialization_queue_on_mysql(mysql_sessions, scenario):
    scenario(mysql_sessions)
