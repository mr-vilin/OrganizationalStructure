import { App } from 'antd';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { LogsPage } from './LogsPage';
beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches:false, addListener:vi.fn(), removeListener:vi.fn(), addEventListener:vi.fn(), removeEventListener:vi.fn() })); vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => vi.unstubAllGlobals());
it('按真实飞书来源、操作和操作者发出日志查询并可重置', async () => {
  const urls:string[]=[]; const user=userEvent.setup({pointerEventsCheck:0});
  vi.stubGlobal('fetch', async (url:string) => { urls.push(url); return Response.json({data:[],meta:{next_cursor:null}}); });
  render(<App><LogsPage /></App>); await waitFor(()=>expect(urls.length).toBeGreaterThan(0));
  await user.type(screen.getByPlaceholderText('操作'),'更新'); await user.type(screen.getByPlaceholderText('操作者'),'ou_actor');
  await user.click(screen.getAllByRole('combobox')[1]); const choices=await screen.findAllByText('飞书同步'); await user.click(choices[choices.length-1]);
  await user.click(screen.getByRole('button',{name:/查\s*询/}));
  await waitFor(()=>expect(urls.at(-1)).toContain('source=feishu')); expect(urls.at(-1)).toContain('action=%E6%9B%B4%E6%96%B0'); expect(urls.at(-1)).toContain('actor=ou_actor');
  await user.click(screen.getByRole('button',{name:/重\s*置/})); await waitFor(()=>expect(urls.at(-1)).toBe('/admin/api/change-logs?limit=100'));
});
it('把日志起止时间转换成 UTC ISO 参数', async () => {
  const urls:string[]=[]; const user=userEvent.setup({pointerEventsCheck:0}); vi.stubGlobal('fetch',async(url:string)=>{urls.push(url);return Response.json({data:[],meta:{next_cursor:null}})}); render(<App><LogsPage/></App>); await waitFor(()=>expect(urls.length).toBeGreaterThan(0)); const [start,end]=screen.getAllByRole('textbox').filter(node=>node.hasAttribute('date-range')); await user.type(start,'2026-09-15 08:00:00'); await user.keyboard('{Enter}'); await user.type(end,'2026-09-15 10:30:00'); await user.keyboard('{Enter}'); await user.click(screen.getByRole('button',{name:/查\s*询/})); await waitFor(()=>expect(urls.at(-1)).toContain('committed_after=')); const parsed=new URL(urls.at(-1)!,'http://local'); expect(parsed.searchParams.get('committed_after')).toMatch(/^2026-09-15T.*Z$/); expect(parsed.searchParams.get('committed_before')).toMatch(/^2026-09-15T.*Z$/);
});
it('对象类型提供真实 membership 与 admin_allowlist 枚举', async () => {
  vi.stubGlobal('fetch',async()=>Response.json({data:[],meta:{next_cursor:null}}));
  render(<App><LogsPage/></App>);
  await waitFor(()=>expect(screen.getAllByRole('combobox').length).toBeGreaterThan(0));
  await userEvent.click(screen.getAllByRole('combobox')[0]);
  expect(await screen.findByText('membership')).toBeTruthy();
  expect(screen.getByText('admin_allowlist')).toBeTruthy();
});
