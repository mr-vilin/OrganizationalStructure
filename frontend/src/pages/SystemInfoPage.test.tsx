import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SystemInfoPage } from './SystemInfoPage';
import { buildInfo } from '../buildInfo';
import { ApiError, request } from '../services/http';

vi.mock('../buildInfo', () => ({ buildInfo: {
  version: '0.1.0', commit: 'a'.repeat(40), dirty: true,
  builtAt: '2026-10-24T00:00:00Z', stage: 'development', releaseDate: null,
} }));

vi.mock('../services/http', async importOriginal => ({
  ...await importOriginal<typeof import('../services/http')>(), request: vi.fn(),
}));

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  vi.mocked(request).mockResolvedValue({ data: buildInfo, meta: {} });
});
afterEach(() => vi.unstubAllGlobals());

describe('系统信息页面', () => {
  it('展示统一产品版本和开发状态，不把构建日期当发布日期', async () => {
    render(<SystemInfoPage />);
    expect(screen.getByRole('heading', { name: '系统信息' })).toBeTruthy();
    expect(screen.getAllByText(`v${buildInfo.version}`).length).toBeGreaterThan(0);
    expect(screen.getAllByText('尚未发布').length).toBeGreaterThan(0);
    expect(screen.getByText(/开发初始阶段（0.x）/)).toBeTruthy();
    expect(screen.getAllByText(buildInfo.dirty === null ? '未知' : buildInfo.dirty ? '包含未提交改动' : '干净提交').length).toBeGreaterThan(0);
    expect(screen.getByText('前端包版本')).toBeTruthy();
    expect(screen.getByText('业务数据版本')).toBeTruthy();
    expect(screen.getByText(/版本升级信息保存位置/)).toBeTruthy();
    expect(screen.getAllByRole('link', { name: /CHANGELOG\.md/ }).length).toBeGreaterThan(0);
    expect(request).toHaveBeenCalledWith('/admin/api/system/version', expect.anything());
  });

  it('前后端不同版本时提示检查部署', async () => {
    vi.mocked(request).mockResolvedValue({ data: { ...buildInfo, version: '0.2.0' }, meta: {} });
    render(<SystemInfoPage />);
    expect(await screen.findByText('前后端构建不一致')).toBeTruthy();
  });

  it('后端读取失败时不声称版本已经确认', async () => {
    vi.mocked(request).mockRejectedValue(new ApiError(503, 'UNAVAILABLE', '服务暂不可用'));
    render(<SystemInfoPage />);
    expect(await screen.findByText('后端运行版本尚未确认')).toBeTruthy();
    expect(screen.getByText('读取失败，未确认')).toBeTruthy();
  });
});
