import { App } from 'antd';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SyncPage } from './SyncPage';

function Address() {
  return <output aria-label="查询参数">{useLocation().search || '无查询参数'}</output>;
}

afterEach(() => vi.unstubAllGlobals());

it('任务深链接轮询到终态后刷新资源，关闭详情同步清除地址参数', async () => {
  let detailReads = 0;
  let jobReads = 0;
  const meta = { dataset_epoch: 'e', data_version: 1, next_cursor: null };
  vi.stubGlobal('fetch', async (url: string) => {
    if (url === '/admin/api/sync/jobs/j1') {
      detailReads += 1;
      return Response.json({ data: { job_id: 'j1', type: 'full', status: detailReads === 1 ? 'running' : 'succeeded', details: [] }, meta });
    }
    if (url.startsWith('/admin/api/sync/jobs?')) jobReads += 1;
    if (url === '/admin/api/status') return Response.json({ data: { initialization_status: 'complete', coverage_status: 'complete', connection: { status: 'connected', scopes: [] }, failed_event_count: 0 }, meta });
    return Response.json({ data: [], meta });
  });
  render(<App><MemoryRouter initialEntries={['/sync?job=j1']}><Address /><SyncPage /></MemoryRouter></App>);
  const dialog = await screen.findByRole('dialog');
  expect(await within(dialog).findByText('执行中')).toBeTruthy();
  await waitFor(() => expect(within(dialog).getByText('成功')).toBeTruthy(), { timeout: 10000 });
  await waitFor(() => expect(jobReads).toBeGreaterThan(1));
  fireEvent.click(within(dialog).getByRole('button', { name: '关闭' }));
  await waitFor(() => expect(screen.getByLabelText('查询参数').textContent).toBe('无查询参数'));
});
