from copy import deepcopy

import pytest

from app.evaluation.fake_feishu import FakeFeishu
from app.evaluation.fixtures import reset_test_database
from app.sync.collector import Collector


def test_multiple_pages_repeatable_and_detached():
    fake = FakeFeishu('multipage')
    first = list(fake.pages('children', department_id='0'))
    assert len(first) == 2 and first[0]['has_more'] is True
    first[0]['items'].clear()
    assert len(list(fake.pages('children', department_id='0'))[0]['items']) == 1
    assert fake.read_count == 2
    assert fake.write_attempt_count == 0


def test_duplicates_reach_real_collector_once():
    fake = FakeFeishu('duplicates')
    candidate = Collector(fake, coverage_verified=True).collect()
    assert set(candidate.departments) == {'0', 'eval_store', 'eval_team'}
    assert list(candidate.employees) == ['eval_user']
    assert candidate.employees['eval_user']['primary_department_id'] == 'eval_team'
    assert candidate.coverage_status == 'complete'


def test_out_of_order_events_preserve_delivery_order_and_latest_detail():
    fake = FakeFeishu('baseline')
    fake.emit('contact.user.updated_v3', 'eval_user')
    fake.emit('contact.user.created_v3', 'eval_user')
    fake.emit('contact.user.updated_v3', 'eval_user')
    events = fake.events
    assert [event['sequence'] for event in events] == [1, 2, 3]
    assert [event['event_type'] for event in events][:2] == ['contact.user.updated_v3', 'contact.user.created_v3']
    events.clear()
    assert len(fake.events) == 3
    assert Collector(fake).event('contact.user.updated_v3', 'eval_user').employees['eval_user']['status'] == 'active'


def test_unreadable_parent_is_pending_in_real_collector():
    candidate = Collector(FakeFeishu('parent_unreadable')).collect()
    assert ('department', 'eval_store') in candidate.pending
    assert 'eval_user' in candidate.employees


def test_scope_narrowing_preserves_old_returned_facts_and_records():
    fake = FakeFeishu('baseline')
    old = fake.detail('user', 'eval_user')
    fake.set_scenario('permission_narrowed')
    assert list(fake.pages('scopes'))[0]['user_ids'] == []
    with pytest.raises(RuntimeError, match='FEISHU_DETAIL_MISSING'):
        fake.detail('user', 'eval_user')
    assert old['department_ids'] == ['eval_team']
    candidate = Collector(fake).collect(previous_users=['eval_user'], previous_departments=['eval_store'])
    assert ('employee', 'eval_user') in candidate.pending
    assert ('department', 'eval_store') in candidate.pending
    assert fake.read_count >= 3


def test_timeout_does_not_return_partial_candidate():
    with pytest.raises(RuntimeError, match='FEISHU_UNAVAILABLE'):
        Collector(FakeFeishu('timeout')).collect()


@pytest.mark.parametrize('kind,identifier', [('user', 'eval_user'), ('department', 'eval_store')])
def test_detail_source_id_checked_like_real_adapter(kind, identifier):
    with pytest.raises(RuntimeError, match='FEISHU_ID_MISMATCH'):
        FakeFeishu('id_mismatch').detail(kind, identifier)


def test_failed_write_attempts_are_independent_and_classified():
    fake = FakeFeishu()
    for method in ['POST', 'PATCH', 'DELETE']:
        with pytest.raises(RuntimeError, match='EVALUATION_FEISHU_WRITE_FORBIDDEN'):
            fake._request(method, 'contact/v3/users/eval_user', json={'name': 'synthetic'})
    assert fake.write_attempt_count == 3
    assert fake.write_attempts_by_method == {'POST': 1, 'PATCH': 1, 'DELETE': 1}
    assert FakeFeishu().write_attempt_count == 0
    assert 'synthetic' not in repr(fake.calls)


def test_fixture_readonly_scenario_fails_closed():
    fake = FakeFeishu('ORG_AGENT_READ_PRIMARY_STORE', responses=[])
    with pytest.raises(RuntimeError, match='EVALUATION_FAKE_RESPONSE_MISSING'):
        list(fake.pages('scopes'))
    assert fake.read_count == 1
    with pytest.raises(ValueError):
        fake.set_scenario('typo')


def test_explicit_raw_responses_are_copied_and_unknown_resources_rejected():
    responses = [{'method': 'detail', 'kind': 'user', 'identifier': 'u',
                  'result': {'user_id': 'u', 'name': '合成', 'department_ids': [], 'status': {'is_resigned': False}, 'orders': []}}]
    original = deepcopy(responses)
    fake = FakeFeishu('custom', responses=responses)
    responses[0]['result']['user_id'] = 'wrong'
    assert fake.detail('user', 'u') == original[0]['result']
    with pytest.raises(ValueError):
        list(fake.pages('unknown'))


@pytest.mark.parametrize('url', ['sqlite://', 'mysql+pymysql://localhost/production', 'postgresql://localhost/org_test'])
def test_reset_rejects_unsafe_url_before_connect(url):
    with pytest.raises(ValueError, match='EVALUATION_TEST_DATABASE_REQUIRED'):
        reset_test_database(url)


@pytest.mark.parametrize('pages', [[], [{'items': [], 'has_more': True}],
    [{'items': [], 'has_more': True, 'page_token': 'same'}, {'items': [], 'has_more': True, 'page_token': 'same'}]])
def test_invalid_pagination_fails_closed(pages):
    fake = FakeFeishu('custom', responses=[{'method': 'pages', 'resource': 'scopes', 'params': {}, 'pages': pages}])
    with pytest.raises(RuntimeError, match='INVALID_PAGINATION'):
        list(fake.pages('scopes'))


def test_timeout_after_first_page_propagates_without_partial_candidate():
    fake = FakeFeishu('custom', responses=[{'method': 'pages', 'resource': 'scopes', 'params': {}, 'pages': [
        {'department_ids': ['eval_store'], 'user_ids': [], 'has_more': True, 'page_token': 'next'},
        {'error': 'FEISHU_UNAVAILABLE'}]}])
    with pytest.raises(RuntimeError, match='FEISHU_UNAVAILABLE'):
        Collector(fake).collect()


def test_explicit_deleted_and_resigned_raw_statuses_reach_collector():
    fake = FakeFeishu('custom', responses=[
        {'method': 'detail', 'kind': 'user', 'identifier': 'gone-user', 'result': {
            'user_id': 'gone-user', 'name': '合成离职', 'status': {'is_resigned': True}, 'department_ids': [], 'orders': []}},
        {'method': 'detail', 'kind': 'department', 'identifier': 'gone-dept', 'result': {
            'open_department_id': 'gone-dept', 'name': '合成删除', 'status': {'is_deleted': True}, 'parent_department_id': '0'}}])
    assert Collector(fake).event('contact.user.deleted_v3', 'gone-user').employees['gone-user']['status'] == 'inactive'
    assert Collector(fake).event('contact.department.deleted_v3', 'gone-dept').departments['gone-dept']['status'] == 'inactive'
