import { App } from 'antd';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import InitializationPage, { type InitializationStatus } from './InitializationPage';
import { AuthGate } from '../components/AuthGate';

afterEach(() => vi.unstubAllGlobals());
const base = (): InitializationStatus => ({ flow_id: 'flow', phase: 'pending', complete: false, checks: [], settings: {} });
const check = (step: number) => ({ step, title: `步骤${step}`, status: 'passed', items: [{ key: 'check', title: `已核验${step}`, status: 'passed', message: '' }] });

it('未初始化管理员只看到全屏向导，工作台内容不挂载', async () => {
  const state = { ...base(), phase: 'cleanup_required' };
  vi.stubGlobal('fetch', async (url: string) => Response.json({ data: url === '/admin/auth/session' ? { open_id: 'ou', csrf_token: 'csrf', initialization_complete: false } : state, meta: {} }));
  render(<App><AuthGate><div>工作台业务资料</div></AuthGate></App>);
  await screen.findByText('需要按新流程重新初始化');
  expect(screen.queryByText('工作台业务资料')).toBeNull();
  expect(screen.getByRole('button', { name: '重新初始化' })).not.toBeNull();
  expect(screen.queryByRole('button', { name: '立即同步' })).toBeNull();
});

it('按顺序自动预检，全部通过后才出现立即同步且等待管理员点击', async () => {
  let state = base();
  const calls: string[] = [];
  vi.stubGlobal('fetch', async (url: string, options: RequestInit) => {
    if (options.method === 'POST') {
      calls.push(url);
      if (url.includes('/checks/')) {
        const step = Number(url.split('/').at(-1));
        state = { ...state, checks: [...state.checks, check(step)], phase: step === 4 ? 'ready' : 'pending' };
      } else if (url.endsWith('/start')) {
        state = { ...state, phase: 'running', job: { job_id: 'job', status: 'running', phase: 'employees', progress: { employees_processed: 8 } } };
        return Response.json({ data: { job_id: 'job' }, meta: {} });
      }
    }
    return Response.json({ data: state, meta: {} });
  });
  render(<App><InitializationPage /></App>);
  expect(screen.queryByRole('button', { name: '立即同步' })).toBeNull();
  const start = await screen.findByRole('button', { name: '立即同步' }, { timeout: 5000 });
  expect(calls).toEqual([1, 2, 3, 4].map(step => `/admin/api/initialization/checks/${step}`));
  expect(screen.queryByText('全企业及无部门人员覆盖验收')).toBeNull();
  expect(screen.queryByRole('button', { name: '保存依据并确认覆盖验收' })).toBeNull();
  fireEvent.click(start);
  await screen.findByText('已采集人员：8');
  expect(calls.filter(url => url.endsWith('/start'))).toHaveLength(1);
  expect(screen.queryByText('初始化完成')).toBeNull();
});

it('失败后必须清理重来，不显示立即同步；历史通过项不会直接放行', async () => {
  let state: InitializationStatus = { ...base(), phase: 'failed', checks: [1, 2, 3, 4].map(check), last_error: { code: 'INTERRUPTED', message: '后台任务已中断' } };
  const mutations: string[] = [];
  vi.stubGlobal('fetch', async (url: string, options: RequestInit) => {
    if (options.method === 'POST') {
      mutations.push(url);
      if (url.endsWith('/restart')) state = { ...base(), flow_id: 'fresh' };
      if (url.includes('/checks/')) state = { ...state, phase: 'precheck_failed', checks: [{ ...check(1), status: 'failed', items: [] }] };
    }
    return Response.json({ data: state, meta: {} });
  });
  render(<App><InitializationPage /></App>);
  const restart = await screen.findByRole('button', { name: '重新开始' });
  expect(screen.queryByRole('button', { name: '立即同步' })).toBeNull();
  fireEvent.click(restart);
  await waitFor(() => expect(mutations).toEqual(['/admin/api/initialization/restart', '/admin/api/initialization/checks/1']));
  expect(screen.queryByRole('button', { name: '立即同步' })).toBeNull();
});

it('后端确认完成后展示人数并由管理员进入系统', async () => {
  const enter = vi.fn();
  vi.stubGlobal('fetch', async () => Response.json({ data: { ...base(), phase: 'complete', complete: true, counts: { departments: 3, employees: 24 } }, meta: {} }));
  render(<App><InitializationPage onComplete={enter} /></App>);
  fireEvent.click(await screen.findByRole('button', { name: '进入系统' }));
  expect(enter).toHaveBeenCalledOnce();
  expect(screen.getByText('已同步 3 个部门、24 位人员，全部校验通过。')).not.toBeNull();
});

const mappingState = (): InitializationStatus => ({
  ...base(), phase: 'precheck_failed',
  settings: { permission_role: 'role', store_attribute: 'store', employee_type_options: { '01': '正式员工', '2': '临时员工' } },
});

it('员工类型按行回显，编辑、增加和删除后保存映射并可重新读取', async () => {
  let state = mappingState();
  const save = vi.fn();
  vi.stubGlobal('fetch', async (_url: string, options: RequestInit) => {
    if (options.method === 'PUT') {
      const settings = JSON.parse(options.body as string);
      save(settings);
      state = { ...state, settings };
    }
    return Response.json({ data: state, meta: {} });
  });
  const view = render(<App><InitializationPage /></App>);
  await screen.findByDisplayValue('正式员工');
  expect(document.querySelector('textarea')).toBeNull();
  fireEvent.change(screen.getByDisplayValue('正式员工'), { target: { value: ' 全职员工 ' } });
  fireEvent.click(screen.getByRole('button', { name: '新增一行' }));
  fireEvent.change(screen.getAllByLabelText('选项 ID')[2], { target: { value: ' 03 ' } });
  fireEvent.change(screen.getAllByLabelText('选项名称')[2], { target: { value: '实习员工' } });
  // 数字键由接口对象枚举在前；删除对应的临时员工行后，其余行的值应保持。
  fireEvent.click(screen.getByRole('button', { name: '删除第 1 行' }));
  fireEvent.click(screen.getByRole('button', { name: '保存设置并重新检查' }));
  await waitFor(() => expect(save).toHaveBeenCalledExactlyOnceWith({
    permission_role: 'role', store_attribute: 'store', employee_type_options: { '01': '全职员工', '03': '实习员工' },
  }));
  view.unmount();
  render(<App><InitializationPage /></App>);
  await screen.findByDisplayValue('全职员工');
  expect(screen.getByDisplayValue('03')).not.toBeNull();
  expect(screen.queryByDisplayValue('临时员工')).toBeNull();
});

it('空白字段及去除首尾空格后的重复 ID 阻止保存，修正后可提交', async () => {
  const save = vi.fn();
  vi.stubGlobal('fetch', async (_url: string, options: RequestInit) => {
    if (options.method === 'PUT') save(JSON.parse(options.body as string));
    return Response.json({ data: mappingState(), meta: {} });
  });
  render(<App><InitializationPage /></App>);
  fireEvent.click(await screen.findByRole('button', { name: '新增一行' }));
  fireEvent.change(screen.getAllByLabelText('选项 ID')[2], { target: { value: '   ' } });
  fireEvent.change(screen.getAllByLabelText('选项名称')[2], { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: '保存设置并重新检查' }));
  await screen.findByText('请填写选项 ID');
  await screen.findByText('请填写选项名称');
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getAllByLabelText('选项 ID')[2], { target: { value: ' 01 ' } });
  fireEvent.change(screen.getAllByLabelText('选项名称')[2], { target: { value: '实习员工' } });
  fireEvent.click(screen.getByRole('button', { name: '保存设置并重新检查' }));
  await screen.findAllByText('选项 ID 不能重复');
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getAllByLabelText('选项 ID')[2], { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: '保存设置并重新检查' }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
});

it('保存失败及状态重新读取后保留编辑内容，删除全部行可保存原契约允许的空映射', async () => {
  const save = vi.fn();
  vi.stubGlobal('fetch', async (_url: string, options: RequestInit) => {
    if (options.method === 'PUT') {
      save(JSON.parse(options.body as string));
      return Response.json({ error: { code: 'UNAVAILABLE', message: '设置暂时无法保存' } }, { status: 503 });
    }
    return Response.json({ data: mappingState(), meta: {} });
  });
  render(<App><InitializationPage /></App>);
  fireEvent.change(await screen.findByDisplayValue('正式员工'), { target: { value: '待保存名称' } });
  fireEvent.click(screen.getByRole('button', { name: '保存设置并重新检查' }));
  await screen.findByText('设置暂时无法保存');
  await waitFor(() => expect((screen.getByRole('button', { name: '新增一行' }) as HTMLButtonElement).disabled).toBe(false));
  expect(screen.getByDisplayValue('待保存名称')).not.toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '删除第 1 行' }));
  fireEvent.click(screen.getByRole('button', { name: '删除第 1 行' }));
  expect(screen.getByText('暂未配置员工类型选项，点击“新增一行”开始填写。')).not.toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '保存设置并重新检查' }));
  await waitFor(() => expect(save).toHaveBeenLastCalledWith({ permission_role: 'role', store_attribute: 'store', employee_type_options: {} }));
});

it('检查期间员工类型输入和增删按钮均禁用', async () => {
  vi.stubGlobal('fetch', async () => Response.json({ data: { ...mappingState(), phase: 'checking', checking_step: 1 }, meta: {} }));
  render(<App><InitializationPage /></App>);
  await screen.findByDisplayValue('正式员工');
  for (const input of [...screen.getAllByLabelText('选项 ID'), ...screen.getAllByLabelText('选项名称')]) expect((input as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: '新增一行' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button', { name: '删除第 1 行' }) as HTMLButtonElement).disabled).toBe(true);
});
