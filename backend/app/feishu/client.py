import time
from urllib.parse import quote

import httpx


class FeishuClient:
    """自建应用；只暴露脱敏错误，不记录响应正文或凭据。"""
    def __init__(self, app_id, app_secret, http=None):
        self.app_id, self.app_secret = app_id, app_secret
        self.http = http or httpx.Client(timeout=20, follow_redirects=False)
        self.tokens = {}

    def _request(self, method, path, token=None, **kwargs):
        try:
            response = self.http.request(method, 'https://open.feishu.cn/open-apis/' + path, headers={'Authorization': 'Bearer ' + token} if token else {}, **kwargs)
            response.raise_for_status()
            payload = response.json()
            if payload.get('code') != 0:
                raise RuntimeError('FEISHU_API_ERROR')
            return payload
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RuntimeError('FEISHU_UNAVAILABLE') from None

    def _token(self, kind):
        cached = self.tokens.get(kind)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        data = self._request('POST', f'auth/v3/{kind}_access_token/internal', json={'app_id': self.app_id, 'app_secret': self.app_secret})
        token = data.get(f'{kind}_access_token')
        if not token:
            raise RuntimeError('FEISHU_TOKEN_MISSING')
        self.tokens[kind] = (token, time.monotonic() + max(0, int(data.get('expire', 0)) - 120))
        return token

    def login(self, code):
        data = self._request('POST', 'authen/v1/oidc/access_token', self._token('app'), json={'grant_type': 'authorization_code', 'code': code}).get('data', {})
        if not data.get('access_token'):
            raise RuntimeError('FEISHU_TOKEN_MISSING')
        return self._request('GET', 'authen/v1/user_info', data['access_token']).get('data', {})

    def pages(self, resource, **params):
        identifier = params.pop('department_id', None)
        path = {'scopes': 'scopes', 'users': 'users/find_by_department', 'custom_attrs': 'custom_attrs', 'children': f'departments/{quote(str(identifier), safe="")}/children'}[resource]
        query = {'user_id_type': 'user_id', 'department_id_type': 'open_department_id', 'page_size': 50, **params}
        if resource == 'custom_attrs':
            query = {'page_size': 100, **params}
        if resource == 'users':
            query['department_id'] = identifier
        if resource == 'children':
            query['fetch_child'] = 'false'
        seen = set()
        while True:
            data = self._request('GET', 'contact/v3/' + path, self._token('tenant'), params=query).get('data')
            if not isinstance(data, dict) or not isinstance(data.get('has_more'), bool):
                raise RuntimeError('INVALID_PAGINATION')
            yield data
            if not data['has_more']:
                break
            token = data.get('page_token')
            if not token or token in seen:
                raise RuntimeError('INVALID_PAGINATION')
            seen.add(token)
            query['page_token'] = token

    def detail(self, kind, identifier):
        path = 'users' if kind == 'user' else 'departments'
        data = self._request('GET', f'contact/v3/{path}/{quote(identifier, safe="")}', self._token('tenant'), params={'user_id_type': 'user_id', 'department_id_type': 'open_department_id'}).get('data', {}).get(kind)
        if not isinstance(data, dict):
            raise RuntimeError('FEISHU_DETAIL_MISSING')
        if data.get('user_id' if kind == 'user' else 'open_department_id') != identifier:
            raise RuntimeError('FEISHU_ID_MISMATCH')
        return data
