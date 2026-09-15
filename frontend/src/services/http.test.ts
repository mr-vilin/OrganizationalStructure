import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request, setCsrfToken } from './http';

afterEach(() => { vi.unstubAllGlobals(); setCsrfToken(null); });

describe('后端请求契约', () => {
  it('写请求带会话与 CSRF，读取数据 envelope', async () => {
    let options: RequestInit | undefined;
    vi.stubGlobal('fetch', async (_url: string, init: RequestInit) => {
      options = init;
      return new Response(JSON.stringify({ data: { id: 'job-1' }, meta: {} }), { status: 202 });
    });
    setCsrfToken('csrf-issued-by-server');
    const result = await request<{ id: string }>('/admin/api/sync/jobs', { method: 'POST', body: { type: 'full' } });
    expect(result.data.id).toBe('job-1');
    expect(options?.credentials).toBe('include');
    expect(new Headers(options?.headers).get('X-CSRF-Token')).toBe('csrf-issued-by-server');
    expect(JSON.parse(options?.body as string)).toEqual({ type: 'full' });
  });

  it('把版本冲突交给页面处理，不把错误当成成功数据', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ error: { code: 'DATASET_CHANGED', message: '数据已更新，请重新预览' } }), { status: 409 }));
    await expect(request('/admin/api/stores')).rejects.toMatchObject({ status: 409, code: 'DATASET_CHANGED', message: '数据已更新，请重新预览' });
  });

  it('代理返回 HTML 时显示可理解的错误', async () => {
    vi.stubGlobal('fetch', async () => new Response('<html>Bad Gateway</html>', { status: 502 }));
    await expect(request('/admin/api/stores')).rejects.toBeInstanceOf(ApiError);
  });

  it('拒绝缺少 data 字段的成功响应', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ unexpected: true }), { status: 200 }));
    await expect(request('/admin/api/stores')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('业务请求鉴权失效时清除 CSRF 并通知门禁', async () => {
    const listener = vi.fn(); window.addEventListener('org-admin-auth-failure', listener);
    vi.stubGlobal('fetch', async () => Response.json({ error: { code: 'ADMIN_SESSION_REQUIRED', message: 'expired' } }, { status: 401 }));
    await expect(request('/admin/api/stores')).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledOnce(); window.removeEventListener('org-admin-auth-failure', listener);
  });
});
