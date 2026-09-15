import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AuthGate } from './AuthGate';

afterEach(() => vi.unstubAllGlobals());

it('未登录时不展示业务页面，只提供飞书登录入口', async () => {
  vi.stubGlobal('fetch', async () => Response.json({ error: { code: 'ADMIN_SESSION_REQUIRED', message: '需要登录' } }, { status: 401 }));
  render(<AuthGate><div>受保护的组织资料</div></AuthGate>);
  const login = await screen.findByRole('link', { name: '使用飞书登录' });
  expect(login.getAttribute('href')).toBe('/admin/auth/login');
  expect(screen.queryByText('受保护的组织资料')).toBeNull();
});

it('后端不可用时不能误入管理页', async () => {
  vi.stubGlobal('fetch', async () => Response.json({ error: { code: 'DATABASE_NOT_CONFIGURED', message: '数据库尚未配置' } }, { status: 503 }));
  render(<AuthGate><div>受保护的组织资料</div></AuthGate>);
  await screen.findByText('数据库尚未配置');
  expect(screen.queryByText('受保护的组织资料')).toBeNull();
});
