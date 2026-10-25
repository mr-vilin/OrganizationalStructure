import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter, useLocation } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { PageErrorBoundary } from './PageErrorBoundary';
import { useState } from 'react';

function Page() {
  if (useLocation().pathname === '/broken') throw new Error('ChunkLoadError');
  return <h1>页面已恢复</h1>;
}

it('资源加载失败时提供中文刷新入口，并在导航后恢复页面', async () => {
  const error = vi.spyOn(console, 'error').mockImplementation(() => {});
  try {
    render(<MemoryRouter initialEntries={['/broken']}><Link to="/organization">切换页面</Link><PageErrorBoundary><Page /></PageErrorBoundary></MemoryRouter>);
    expect(await screen.findByText('页面暂时无法加载')).toBeTruthy();
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: '切换页面' }));
    expect(await screen.findByRole('heading', { name: '页面已恢复' })).toBeTruthy();
  } finally {
    error.mockRestore();
  }
});

it('仅切换任务详情查询参数时保留页面筛选状态', () => {
  function StatefulPage() {
    const [filter, setFilter] = useState('全部');
    return <><button onClick={() => setFilter('失败')}>筛选失败</button><output aria-label="当前筛选">{filter}</output><Link to="/sync?job=j1">打开任务详情</Link></>;
  }
  render(<MemoryRouter initialEntries={['/sync']}><PageErrorBoundary><StatefulPage /></PageErrorBoundary></MemoryRouter>);
  fireEvent.click(screen.getByRole('button', { name: '筛选失败' }));
  fireEvent.click(screen.getByRole('link', { name: '打开任务详情' }));
  expect(screen.getByLabelText('当前筛选').textContent).toBe('失败');
});
