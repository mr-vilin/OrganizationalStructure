import httpx
import pytest


def test_oidc_uses_app_token_then_nested_user_token():
    from app.feishu.client import FeishuClient
    def respond(request):
        if request.url.path.endswith('/app_access_token/internal'):
            return httpx.Response(200, json={"code": 0, "app_access_token": "app-token", "expire": 7200})
        if request.url.path.endswith('/oidc/access_token'):
            assert request.headers['authorization'] == 'Bearer app-token'
            return httpx.Response(200, json={"code": 0, "data": {"access_token": "user-token", "expires_in": 7200}})
        assert request.url.path.endswith('/user_info')
        assert request.headers['authorization'] == 'Bearer user-token'
        return httpx.Response(200, json={"code": 0, "data": {"open_id": "ou_a", "user_id": "u", "tenant_key": "tenant"}})
    api = FeishuClient('app', 'secret', httpx.Client(transport=httpx.MockTransport(respond)))
    assert api.login('code')['tenant_key'] == 'tenant'


def test_pagination_rejects_repeated_token_and_masks_upstream_errors():
    from app.feishu.client import FeishuClient
    def respond(request):
        if request.url.path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "sensitive", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"has_more": True, "page_token": "same", "department_ids": []}})
    api = FeishuClient('a', 's', httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(RuntimeError, match='INVALID_PAGINATION'):
        list(api.pages('scopes'))


def test_event_identity_and_missing_object_are_not_silently_accepted():
    from app.feishu.events import normalize_event
    payload = {"header": {"event_id": "e", "event_type": "contact.user.deleted_v3", "app_id": "a", "tenant_key": "t"}, "event": {"object": {}}}
    result = normalize_event(payload, 'a', 't')
    assert result['status'] == 'failed'
    assert result['payload']['error_code'] == 'EVENT_OBJECT_ID_MISSING'
    with pytest.raises(ValueError, match='EVENT_IDENTITY_MISMATCH'):
        normalize_event(payload, 'other', 't')


def test_scope_change_is_processable_without_object_id():
    from app.feishu.events import normalize_event
    result=normalize_event({'header':{'event_id':'scope','event_type':'contact.scope.updated_v3','app_id':'a','tenant_key':'t'},'event':{}},'a','t')
    assert result['status']=='queued'
