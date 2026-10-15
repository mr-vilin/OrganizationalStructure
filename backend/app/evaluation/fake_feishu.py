"""完全离线的 Collector 适配器；原始场景固定，读取与写尝试证据独立记录。"""
from collections import Counter
from copy import deepcopy
from typing import Any, Iterable


_DEPARTMENTS = {
    'eval_store': {'open_department_id': 'eval_store', 'parent_department_id': '0', 'name': '合成门店', 'status': {'is_deleted': False}},
    'eval_team': {'open_department_id': 'eval_team', 'parent_department_id': 'eval_store', 'name': '合成小组', 'status': {'is_deleted': False}},
}
_USER = {'user_id': 'eval_user', 'name': '合成员工', 'department_ids': ['eval_team'],
         'orders': [{'department_id': 'eval_team', 'is_primary_dept': True}],
         'status': {'is_resigned': False, 'is_exited': False}}
_SAFE_ERRORS = {'FEISHU_UNAVAILABLE', 'FEISHU_DETAIL_MISSING', 'FEISHU_API_ERROR', 'INVALID_PAGINATION'}
_READ_ONLY = {'ORG_AGENT_READ_PRIMARY_STORE', 'ORG_AGENT_READ_NOT_IN_STORE'}


def _scenario(name):
    """仅组装显式上游数据，不计算任何组织归属或预期状态。"""
    if name in _READ_ONLY:
        return []
    if name not in {'baseline', 'multipage', 'duplicates', 'parent_unreadable', 'permission_narrowed', 'timeout', 'id_mismatch'}:
        raise ValueError('EVALUATION_FAKE_SCENARIO_UNKNOWN')
    if name == 'permission_narrowed':
        return [{'method': 'pages', 'resource': resource, 'params': params, 'pages': [result]}
                for resource, params, result in [
                    ('scopes', {}, {'department_ids': [], 'user_ids': [], 'group_ids': [], 'has_more': False}),
                    ('children', {'department_id': '0'}, {'items': [], 'has_more': False}),
                    ('users', {'department_id': '0'}, {'items': [], 'has_more': False})]]
    scopes = {'department_ids': [], 'user_ids': ['eval_user'], 'group_ids': [], 'has_more': False}
    rows = [{'method': 'pages', 'resource': 'scopes', 'params': {}, 'pages': [scopes]}]
    for department, children, users in [('0', ['eval_store'], []), ('eval_store', ['eval_team'], []), ('eval_team', [], ['eval_user'])]:
        child_items = [{'open_department_id': item} for item in children]
        user_items = [{'user_id': item} for item in users]
        if name == 'duplicates':
            child_items *= 2
            user_items *= 2
        pages = [{'items': child_items, 'has_more': False}]
        if name == 'multipage' and department == '0':
            pages = [{'items': child_items, 'has_more': True, 'page_token': 'eval-page-2'}, {'items': [], 'has_more': False}]
        rows += [{'method': 'pages', 'resource': 'children', 'params': {'department_id': department}, 'pages': pages},
                 {'method': 'pages', 'resource': 'users', 'params': {'department_id': department}, 'pages': [{'items': user_items, 'has_more': False}]}]
    if name == 'timeout':
        rows[1] = {'method': 'pages', 'resource': 'children', 'params': {'department_id': '0'}, 'error': 'FEISHU_UNAVAILABLE'}
    for identifier, raw in _DEPARTMENTS.items():
        row = {'method': 'detail', 'kind': 'department', 'identifier': identifier, 'result': deepcopy(raw)}
        if name == 'parent_unreadable' and identifier == 'eval_store':
            # 先从子组采集，再由祖先补全路径遇到权限错误。
            row = {'method': 'detail', 'kind': 'department', 'identifier': identifier, 'error': 'FEISHU_DETAIL_MISSING'}
        elif name == 'id_mismatch':
            row['result']['open_department_id'] = 'wrong-source'
        rows.append(row)
    if name == 'parent_unreadable':
        rows[1]['pages'] = [{'items': [{'open_department_id': 'eval_team'}], 'has_more': False}]
    raw_user = deepcopy(_USER)
    if name == 'id_mismatch':
        raw_user['user_id'] = 'wrong-source'
    rows.append({'method': 'detail', 'kind': 'user', 'identifier': 'eval_user', 'result': raw_user})
    return rows


class FakeFeishu:
    """与 FeishuClient.pages/detail 同形；每个 case 必须新建实例。

    responses 是纯数据行数组：pages 行含 resource/params/pages；detail 行含
    kind/identifier/result；任一行可用 error 指定安全错误码。未知读取关闭失败。
    emit 只排队事件通知，不改写当前上游事实；场景切换保留调用/事件证据。
    """
    def __init__(self, scenario_id: str = 'baseline', *, responses: list[dict[str, Any]] | None = None):
        self._calls: list[dict] = []
        self._events: list[dict] = []
        self._writes: Counter = Counter()
        self.scenario_id = scenario_id
        self._responses = deepcopy(_scenario(scenario_id) if responses is None else responses)

    @property
    def calls(self):
        return deepcopy(self._calls)

    @property
    def events(self):
        return deepcopy(self._events)

    @property
    def read_count(self):
        return sum(call['method'] in {'pages', 'detail'} for call in self._calls)

    @property
    def write_attempt_count(self):
        return sum(self._writes.values())

    @property
    def write_attempts_by_method(self):
        return dict(self._writes)

    def set_scenario(self, name: str) -> None:
        responses = _scenario(name)
        self.scenario_id, self._responses = name, deepcopy(responses)

    def _response(self, **selector):
        self._calls.append({'sequence': len(self._calls) + 1, **deepcopy(selector)})
        for row in self._responses:
            if all(row.get(key) == value for key, value in selector.items()):
                if row.get('error'):
                    if row['error'] not in _SAFE_ERRORS:
                        raise ValueError('EVALUATION_FAKE_ERROR_UNKNOWN')
                    raise RuntimeError(row['error'])
                return deepcopy(row)
        if self.scenario_id == 'permission_narrowed' and selector['method'] == 'detail':
            raise RuntimeError('FEISHU_DETAIL_MISSING')
        raise RuntimeError('EVALUATION_FAKE_RESPONSE_MISSING')

    def pages(self, resource: str, **params) -> Iterable[dict]:
        if resource not in {'scopes', 'children', 'users'}:
            raise ValueError('EVALUATION_FAKE_RESOURCE_UNKNOWN')
        row = self._response(method='pages', resource=resource, params=params)
        seen = set()
        pages = row.get('pages', [])
        for index, page in enumerate(pages):
            if isinstance(page, dict) and 'error' in page:
                if page['error'] not in _SAFE_ERRORS:
                    raise ValueError('EVALUATION_FAKE_ERROR_UNKNOWN')
                raise RuntimeError(page['error'])
            if not isinstance(page, dict) or type(page.get('has_more')) is not bool:
                raise RuntimeError('INVALID_PAGINATION')
            yield deepcopy(page)
            if not page['has_more']:
                return
            token = page.get('page_token')
            if not token or token in seen or index == len(pages) - 1:
                raise RuntimeError('INVALID_PAGINATION')
            seen.add(token)
        raise RuntimeError('INVALID_PAGINATION')

    def detail(self, kind: str, identifier: str) -> dict:
        if kind not in {'department', 'user'}:
            raise ValueError('EVALUATION_FAKE_KIND_UNKNOWN')
        value = self._response(method='detail', kind=kind, identifier=identifier).get('result')
        if not isinstance(value, dict):
            raise RuntimeError('FEISHU_DETAIL_MISSING')
        if value.get('user_id' if kind == 'user' else 'open_department_id') != identifier:
            raise RuntimeError('FEISHU_ID_MISMATCH')
        return value

    def emit(self, event_type: str, identifier: str) -> None:
        self._events.append({'sequence': len(self._events) + 1, 'event_type': event_type, 'identifier': identifier})

    def _request(self, method: str, path: str, token=None, **kwargs):
        """阻断 FeishuClient 的低层写入口，凭据/正文不进入证据。"""
        method = method.upper()
        self._calls.append({'sequence': len(self._calls) + 1, 'method': method})
        if method not in {'GET', 'HEAD', 'OPTIONS'}:
            self._writes[method] += 1
            raise RuntimeError('EVALUATION_FEISHU_WRITE_FORBIDDEN')
        raise RuntimeError('EVALUATION_FAKE_RESPONSE_MISSING')
