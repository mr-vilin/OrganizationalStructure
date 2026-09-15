import { App } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { OrganizationPage } from './OrganizationPage';
const department = { id:'d1', parent_id:null, name:'总部', path:['总部'], status:'active', sync_quality:'complete', is_virtual_root:false, is_store:false, store_code:null, notes:null };
beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches:false, addListener:vi.fn(), removeListener:vi.fn(), addEventListener:vi.fn(), removeEventListener:vi.fn() })); vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }); });
afterEach(() => vi.unstubAllGlobals());
it('子资源冲突后重读父子整组，且从不发送无版本员工请求', async () => {
  const employeeUrls:string[]=[]; let departmentReads=0; let employeeReads=0;
  vi.stubGlobal('fetch', async (url:string) => {
    if(url.startsWith('/admin/api/departments')) { departmentReads++; const version=departmentReads===1?1:2; return Response.json({data:[department],meta:{dataset_epoch:'epoch',data_version:version,next_cursor:null}}); }
    if(url.startsWith('/admin/api/employees')) { employeeUrls.push(url); employeeReads++; if(employeeReads===1) return Response.json({error:{code:'DATASET_CHANGED',message:'changed'}},{status:409}); return Response.json({data:[],meta:{dataset_epoch:'epoch',data_version:2,next_cursor:null}}); }
    throw new Error(url);
  });
  render(<App><MemoryRouter><OrganizationPage /></MemoryRouter></App>); await userEvent.click(await screen.findByText('总部')); await waitFor(()=>expect(departmentReads).toBe(2)); await waitFor(()=>expect(employeeUrls.some(url=>url.includes('data_version=2'))).toBe(true)); expect(employeeUrls.every(url=>url.includes('dataset_epoch=epoch')&&url.includes('data_version='))).toBe(true);
  expect(employeeReads).toBe(2);
});
it('搜索深层节点保留并展开祖先，清除搜索后树仍可操作', async () => {
  const rows=[department,{...department,id:'d2',parent_id:'d1',name:'区域'},{...department,id:'d3',parent_id:'d2',name:'人民路店'}];
  vi.stubGlobal('fetch', async (url:string) => url.startsWith('/admin/api/departments') ? Response.json({data:rows,meta:{dataset_epoch:'e',data_version:1,next_cursor:null}}) : Response.json({data:[],meta:{dataset_epoch:'e',data_version:1,next_cursor:null}}));
  render(<App><MemoryRouter><OrganizationPage /></MemoryRouter></App>);
  const root = await screen.findByRole('treeitem', { name: /总部/ });
  const switcher = root.querySelector('.ant-tree-switcher') as HTMLElement;
  await userEvent.click(switcher);
  await waitFor(() => expect(screen.queryByText('区域')).toBeNull());
  await userEvent.click(switcher);
  expect(await screen.findByText('区域')).toBeTruthy();
  const search=screen.getByPlaceholderText('搜索部门名称或 ID'); await userEvent.type(search,'人民路'); expect(await screen.findByText('总部')).toBeTruthy(); expect(screen.getByText('区域')).toBeTruthy(); expect(screen.getByText('人民路店')).toBeTruthy(); await userEvent.clear(search); await userEvent.click(screen.getByText('区域')); expect(screen.getByText('人民路店')).toBeTruthy();
});
it('持续版本冲突在有限整组重试后停止并提供手动重试', async () => {
  let departmentReads=0; let employeeReads=0;
  vi.stubGlobal('fetch', async (url:string) => { if(url.startsWith('/admin/api/departments')) { departmentReads++; return Response.json({data:[department],meta:{dataset_epoch:'e',data_version:departmentReads,next_cursor:null}}); } employeeReads++; return Response.json({error:{code:'DATASET_CHANGED',message:'数据持续变化'}},{status:409}); });
  render(<App><MemoryRouter><OrganizationPage /></MemoryRouter></App>); await userEvent.click(await screen.findByText('总部')); await waitFor(()=>expect(departmentReads).toBe(2)); await waitFor(()=>expect(employeeReads).toBe(2)); await screen.findByText('数据持续变化'); await userEvent.click(screen.getByRole('button',{name:/重\s*试/})); await waitFor(()=>expect(departmentReads).toBeGreaterThan(2));
});
it('父页面批量提交冲突后保留完整草稿并以新版本重提', async () => {
  const rows=[department,{...department,id:'d2',parent_id:'d1',name:'分店',path:['总部','分店'],notes:'分店备注'}];
  const previews:any[]=[]; let departmentReads=0; let applyReads=0;
  vi.stubGlobal('fetch',async(url:string,init?:RequestInit)=>{
    if(url.startsWith('/admin/api/departments')) { departmentReads++; return Response.json({data:rows.map(row=>({...row})),meta:{dataset_epoch:'e',data_version:departmentReads,next_cursor:null}}); }
    if(url.endsWith('/preview')) { const body=JSON.parse(String(init?.body)); previews.push(body); return Response.json({data:{changes:body.changes,affected_employee_count:2},meta:{}}); }
    if(url.endsWith('/apply')) { applyReads++; return applyReads===1 ? Response.json({error:{code:'DATASET_CHANGED',message:'changed'}},{status:409}) : Response.json({data:{},meta:{}}); }
    throw new Error(url);
  });
  render(<App><MemoryRouter><OrganizationPage /></MemoryRouter></App>);
  const checks=await screen.findAllByRole('checkbox');
  await userEvent.click(checks[0]); await userEvent.click(checks[1]);
  await userEvent.click(screen.getByRole('button',{name:/批量设置/}));
  const note=screen.getByDisplayValue('分店备注'); await userEvent.clear(note); await userEvent.type(note,'冲突后保留');
  await userEvent.click(screen.getByRole('button',{name:'预览影响'}));
  await userEvent.click(await screen.findByRole('button',{name:'确认提交'}));
  await waitFor(()=>expect(departmentReads).toBe(2));
  expect(screen.getByDisplayValue('冲突后保留')).toBeTruthy();
  const retry=screen.getByText('预览影响').closest('button')!;
  await waitFor(()=>expect(retry.disabled).toBe(false));
  await userEvent.click(retry);
  await waitFor(()=>expect(previews).toHaveLength(2));
  expect(previews[1].data_version).toBe(2); expect(previews[1].changes).toHaveLength(2);
  await userEvent.click(await screen.findByRole('button',{name:/确认提交/}));
  await waitFor(()=>expect(applyReads).toBe(2));
});
