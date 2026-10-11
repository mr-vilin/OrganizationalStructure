import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SystemInfoPage } from './SystemInfoPage';

beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })); });
afterEach(() => vi.unstubAllGlobals());

describe('系统信息页面', () => {
  it('展示产品版本、版本分层、架构和版本台账入口', () => {
    render(<SystemInfoPage />);
    expect(screen.getByRole('heading', { name: '系统信息' })).toBeTruthy();
    expect(screen.getAllByText('v2.8.62').length).toBeGreaterThan(0);
    expect(screen.getByText('前端包版本')).toBeTruthy();
    expect(screen.getByText('业务数据版本')).toBeTruthy();
    expect(screen.getByText(/版本升级信息保存位置/)).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /CHANGELOG\.md/ }).length).toBeGreaterThan(0);
  });
});
