# Task 3 new-file review package (no Git baseline)

## frontend/index.html
```
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#1677ff" />
    <title>组织服务 · 管理工作台</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>

```

## frontend/package.json
```
{
  "name": "organization-directory-web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -b && vite build",
    "preview": "vite preview --host 127.0.0.1",
    "test": "vitest run"
  },
  "dependencies": {
    "@ant-design/icons": "6.3.4",
    "antd": "6.6.4",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "react-router-dom": "7.18.3"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.7",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "6.1.1",
    "jsdom": "30.0.1",
    "typescript": "5.9.3",
    "vite": "8.3.0",
    "vitest": "5.0.0"
  }
}

```

## frontend/src/App.tsx
```
import { useState } from 'react';
import { ApartmentOutlined, AuditOutlined, LogoutOutlined, MenuOutlined, SettingOutlined, ShopOutlined, SyncOutlined } from '@ant-design/icons';
import { App as AntApp, Button, Drawer, Layout, Menu, Space, Tag, Typography } from 'antd';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { request } from './services/http'; import { OrganizationPage } from './pages/OrganizationPage'; import { EmployeePage } from './pages/EmployeePage'; import { StoresPage } from './pages/StoresPage'; import { SyncPage } from './pages/SyncPage'; import { LogsPage } from './pages/LogsPage'; import { SettingsPage } from './pages/SettingsPage';
const items=[{key:'/organization',icon:<ApartmentOutlined/>,label:'组织架构'},{key:'/stores',icon:<ShopOutlined/>,label:'门店管理'},{key:'/sync',icon:<SyncOutlined/>,label:'同步中心'},{key:'/logs',icon:<AuditOutlined/>,label:'变更日志'},{key:'/settings',icon:<SettingOutlined/>,label:'管理设置'}];
function Navigation(){const nav=useNavigate();const loc=useLocation();return <Menu mode="inline" selectedKeys={[items.find(i=>loc.pathname.startsWith(i.key))?.key??'/organization']} items={items} onClick={e=>nav(e.key)}/>}
export function App(){const [mobile,setMobile]=useState(false);const {message}=AntApp.useApp();async function logout(){try{await request('/admin/auth/logout',{method:'POST'});location.assign('/');}catch(e){message.error(e instanceof Error?e.message:'退出失败')}}return <Layout className="app-shell"><Layout.Sider className="desktop-sider" width={208} theme="light"><div className="brand"><span>组</span><div><strong>组织服务</strong><small>ORGANIZATION</small></div></div><Navigation/><div className="sider-foot"><Tag>单企业实例</Tag><small>内部管理工作台</small></div></Layout.Sider><Layout><Layout.Header><Button className="mobile-menu" icon={<MenuOutlined/>} onClick={()=>setMobile(true)}/><Typography.Text strong>组织管理工作台</Typography.Text><Space><Tag color="blue">管理员</Tag><Button type="text" icon={<LogoutOutlined/>} onClick={logout}>退出</Button></Space></Layout.Header><Layout.Content><Routes><Route path="/organization" element={<OrganizationPage/>}/><Route path="/employees/:id" element={<EmployeePage/>}/><Route path="/stores" element={<StoresPage/>}/><Route path="/sync" element={<SyncPage/>}/><Route path="/logs" element={<LogsPage/>}/><Route path="/settings" element={<SettingsPage/>}/><Route path="*" element={<Navigate to="/organization" replace/>}/></Routes></Layout.Content></Layout><Drawer title="组织服务" placement="left" size={240} open={mobile} onClose={()=>setMobile(false)}><Navigation/></Drawer></Layout>}

```

## frontend/src/components/AuthGate.test.tsx
```
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

```

## frontend/src/components/AuthGate.tsx
```
import { createContext, type ReactNode, useContext, useEffect } from 'react';
import { Button, Result, Space, Spin } from 'antd';
import { ApartmentOutlined } from '@ant-design/icons';
import { setCsrfToken } from '../services/http';
import { useResource } from '../services/useResource';

interface AdminSession { open_id: string; csrf_token: string }
const SessionContext = createContext<AdminSession | null>(null);
export const useAdminSession = () => useContext(SessionContext);

export function AuthGate({ children }: { children: ReactNode }) {
  const session = useResource<AdminSession>('/admin/auth/session');
  useEffect(() => {
    setCsrfToken(session.data?.csrf_token ?? null);
    return () => setCsrfToken(null);
  }, [session.data]);

  if (session.data) return <SessionContext.Provider value={session.data}>{children}</SessionContext.Provider>;
  if (session.loading || !session.error) return <div style={{ padding: '25vh 24px', textAlign: 'center' }}><Spin size="large" /><p>正在验证管理员身份…</p></div>;
  const needsLogin = session.error.status === 401;
  const forbidden = session.error.status === 403;
  return <main className="login-page" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#f5f7fa', padding: 24 }}>
    <div style={{ width: 'min(560px, 100%)', background: '#fff', borderRadius: 12, padding: '24px 8px', border: '1px solid #e7eaf0' }}>
      <Result
        icon={needsLogin ? <ApartmentOutlined style={{ color: '#1677ff' }} /> : undefined}
        status={needsLogin ? 'info' : forbidden ? '403' : 'warning'}
        title={needsLogin ? '组织服务' : forbidden ? '暂无管理权限' : '暂时无法进入工作台'}
        subTitle={needsLogin ? '使用企业飞书身份登录，仅管理员白名单成员可访问。' : session.error.message}
        extra={<Space wrap><Button type="primary" href="/admin/auth/login">使用飞书登录</Button><Button onClick={session.reload}>重新检查</Button></Space>}
      />
    </div>
  </main>;
}

```

## frontend/src/components/PageHeader.tsx
```
import type { ReactNode } from 'react';
export function PageHeader({ title, description, extra }: { title: string; description: string; extra?: ReactNode }) { return <header className="page-header"><div><div className="breadcrumb">工作台 / {title}</div><h1>{title}</h1><p>{description}</p></div>{extra}</header>; }

```

## frontend/src/components/ResourceState.tsx
```
import type { ReactNode } from 'react';
import { Alert, Button, Empty, Skeleton } from 'antd';
import type { ApiError } from '../services/http';

export function ResourceState({ loading, error, empty, reload, children }: { loading: boolean; error: ApiError | null; empty?: boolean; reload: () => void; children: ReactNode }) {
  if (loading) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (error) return <Alert showIcon type="error" title={error.status === 503 ? '数据尚未就绪' : '读取失败'} description={error.message} action={<Button onClick={reload}>重试</Button>} />;
  if (empty) return <Empty description="暂无数据" />;
  return <>{children}</>;
}

```

## frontend/src/components/StoreEditor.tsx
```
import { useEffect, useMemo, useState } from 'react';
import { Alert, App, Button, Descriptions, Drawer, Form, Input, Modal, Space, Switch } from 'antd';
import type { Department, StoreChange } from '../domain';
import { stableFingerprint } from '../domain';
import { ApiError, request } from '../services/http';

export function StoreEditor({ department, dataVersion, open, onClose, onSaved }: { department: Department | null; dataVersion?: number; open: boolean; onClose: () => void; onSaved: () => void }) {
  const { message } = App.useApp();
  const [form] = Form.useForm<StoreChange>(); const [preview, setPreview] = useState<{ change: StoreChange; affected: number; version: number; fingerprint: string } | null>(null); const [busy, setBusy] = useState(false); const [conflict, setConflict] = useState(false);
  useEffect(() => { if (department && open) { form.setFieldsValue({ department_id: department.id, is_store: Boolean(department.is_store), store_code: department.store_code, notes: department.notes }); setPreview(null); setConflict(false); } }, [department, open, form]);
  const watchedValues = Form.useWatch([], form);
  const currentFingerprint = useMemo(() => stableFingerprint(form.getFieldsValue(true)), [form, watchedValues]);
  async function doPreview() { if (dataVersion === undefined) return; const change = await form.validateFields(); setBusy(true); setConflict(false); try { const r = await request<{ changes?: StoreChange[]; affected_employee_count?: number }>('/admin/api/stores/batch/preview', { method: 'POST', body: { data_version: dataVersion, changes: [change] } }); const normalized = r.data.changes?.[0] ?? change; form.setFieldsValue(normalized); setPreview({ change: normalized, affected: r.data.affected_employee_count ?? 0, version: dataVersion, fingerprint: stableFingerprint(normalized) }); } catch (e) { message.error(e instanceof Error ? e.message : '预览失败'); } finally { setBusy(false); } }
  async function apply() { if (!preview || preview.version !== dataVersion || preview.fingerprint !== currentFingerprint) return; setBusy(true); try { await request('/admin/api/stores/batch/apply', { method: 'POST', body: { data_version: preview.version, changes: [preview.change] } }); message.success('门店资料已保存'); onSaved(); onClose(); } catch (e) { if (e instanceof ApiError && e.status === 409) { setConflict(true); setPreview(null); } else message.error(e instanceof Error ? e.message : '保存失败'); } finally { setBusy(false); } }
  return <Drawer title={`编辑门店 · ${department?.name ?? ''}`} open={open} onClose={onClose} destroyOnHidden size={520} footer={<Space><Button onClick={onClose}>取消</Button><Button loading={busy} onClick={doPreview}>预览影响</Button><Button type="primary" loading={busy} disabled={!preview || preview.version !== dataVersion || preview.fingerprint !== currentFingerprint} onClick={apply}>确认保存</Button></Space>}>
    {conflict && <Alert className="block-gap" type="warning" showIcon title="数据已更新，请重新预览" description="表单内容已保留。" />}
    <Form form={form} layout="vertical"><Form.Item name="department_id" hidden><Input /></Form.Item><Form.Item name="is_store" label="标记为门店" valuePropName="checked"><Switch disabled={department?.id === 'root'} /></Form.Item><Form.Item name="store_code" label="门店编码"><Input placeholder="留空将清除编码" /></Form.Item><Form.Item name="notes" label="备注"><Input.TextArea rows={4} /></Form.Item></Form>
    {preview && <Modal title="变更预览" open footer={null} onCancel={() => setPreview(null)}><Descriptions column={1} items={[{ key: 'name', label: '部门', children: department?.name }, { key: 'store', label: '门店状态', children: preview.change.is_store ? '门店' : '普通部门' }, { key: 'affected', label: '受影响员工', children: `${preview.affected} 人` }]} /><Alert showIcon type="info" title="确认后将按此预览提交" /></Modal>}
  </Drawer>;
}

```

## frontend/src/domain.test.ts
```
import { describe, expect, it } from 'vitest';
import { primaryStoreLabel, previewMatches } from './domain';

describe('管理端领域规则', () => {
  it('只有预览版本和当前版本一致时才允许提交', () => {
    expect(previewMatches({ dataVersion: 42, fingerprint: 'a' }, 42, 'a')).toBe(true);
    expect(previewMatches({ dataVersion: 42, fingerprint: 'a' }, 43, 'a')).toBe(false);
    expect(previewMatches({ dataVersion: 42, fingerprint: 'a' }, 42, 'b')).toBe(false);
  });

  it('区分未归属门店与无法判断', () => {
    expect(primaryStoreLabel('not_in_store')).toBe('不在门店');
    expect(primaryStoreLabel('unknown')).toBe('暂无法判断');
  });
});

```

## frontend/src/domain.ts
```
export type PrimaryStoreStatus = 'resolved' | 'not_in_store' | 'unknown' | 'inconsistent' | 'inactive';
export interface Department { id: string; name: string; parent_id?: string | null; path?: string[] | string; active?: boolean; is_active?: boolean; is_store?: boolean; store_code?: string | null; notes?: string | null; employee_count?: number }
export interface Employee { id: string; name: string; open_id?: string; active?: boolean; is_active?: boolean; department_id?: string; departments?: Array<{ id?: string; department_id?: string; name?: string; is_primary?: boolean }>; stores?: Array<{ id?: string; store_id?: string; name?: string }>; primary_store?: { id?: string; store_id?: string; name?: string } | null; primary_store_id?: string | null; primary_store_status?: PrimaryStoreStatus }
export interface Store extends Department { employee_count?: number; primary_employee_count?: number }
export interface SyncJob { id?: string; job_id?: string; type: string; status: string; stage?: string; root_department_id?: string | null; attempt_count?: number; created_at?: string; updated_at?: string; error_code?: string | null; processed_department_count?: number; processed_employee_count?: number; total_count?: number | null; [key: string]: unknown }
export interface ChangeLog { id: string | number; object_type?: string; object_id?: string; object_name?: string; action?: string; source?: string; actor?: string; actor_open_id?: string; job_id?: string; committed_at?: string; before?: unknown; after?: unknown }
export interface ApiClient { id?: string; client_id?: string; name: string; revoked_at?: string | null; active?: boolean; last_used_at?: string | null }
export interface PreviewToken { dataVersion: number; fingerprint: string }
export interface StoreChange { department_id: string; is_store: boolean; store_code?: string | null; notes?: string | null }

export function stableFingerprint(value: unknown) { return JSON.stringify(value); }
export function previewMatches(token: PreviewToken | null, dataVersion: number | undefined, fingerprint: string) { return Boolean(token && dataVersion !== undefined && token.dataVersion === dataVersion && token.fingerprint === fingerprint); }
export function primaryStoreLabel(status?: PrimaryStoreStatus) {
  return ({ resolved: '已解析', not_in_store: '不在门店', unknown: '暂无法判断', inconsistent: '数据不一致', inactive: '员工已失效' } as Record<string, string>)[status ?? ''] ?? '暂无法判断';
}
export function isActive(value: { active?: boolean; is_active?: boolean }) { return value.active ?? value.is_active ?? true; }
export function formatTime(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(date); }

```

## frontend/src/main.tsx
```
import React from 'react'; import ReactDOM from 'react-dom/client'; import { BrowserRouter } from 'react-router-dom'; import { App as AntApp, ConfigProvider } from 'antd'; import zhCN from 'antd/locale/zh_CN'; import { AuthGate } from './components/AuthGate'; import { App } from './App'; import './styles.css';
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><ConfigProvider locale={zhCN} theme={{token:{colorPrimary:'#1677ff',borderRadius:8,colorBgLayout:'#f5f7fa',fontFamily:'Microsoft YaHei, PingFang SC, system-ui, sans-serif'}}}><AntApp><AuthGate><BrowserRouter><App/></BrowserRouter></AuthGate></AntApp></ConfigProvider></React.StrictMode>);

```

## frontend/src/pages/EmployeePage.tsx
```
import { Button, Card, Descriptions, List, Result, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import type { Employee } from '../domain';
import { isActive, primaryStoreLabel } from '../domain';
import { useResource } from '../services/useResource';
import { ResourceState } from '../components/ResourceState';
import { PageHeader } from '../components/PageHeader';
export function EmployeePage() { const { id } = useParams(); const nav = useNavigate(); const resource = useResource<Employee>(id ? `/admin/api/employees/${encodeURIComponent(id)}` : null); const e = resource.data; return <><PageHeader title="人员详情" description="解释部门关系、全部门店与唯一主门店的派生结果。" extra={<Button icon={<ArrowLeftOutlined />} onClick={() => nav('/organization')}>返回组织</Button>} /><ResourceState {...resource}>{e ? <div className="detail-grid"><Card><Descriptions title={e.name} column={{ xs: 1, md: 2 }} items={[{ key: 'id', label: '员工 ID', children: e.id }, { key: 'active', label: '状态', children: <Tag color={isActive(e) ? 'success' : 'default'}>{isActive(e) ? '在职' : '失效'}</Tag> }, { key: 'status', label: '主门店解析', children: primaryStoreLabel(e.primary_store_status) }, { key: 'primary', label: '主门店', children: e.primary_store?.name ?? e.primary_store_id ?? '—' }]} /><Result status={e.primary_store_status === 'resolved' ? 'success' : 'info'} title={primaryStoreLabel(e.primary_store_status)} subTitle="主门店仅由唯一飞书主部门向上寻找最近门店派生；数组顺序不代表主归属。" /></Card><Card title="部门关系"><List dataSource={e.departments ?? []} locale={{ emptyText: '暂无部门关系' }} renderItem={d => <List.Item extra={d.is_primary && <Tag color="blue">主部门</Tag>}>{d.name ?? d.department_id ?? d.id}</List.Item>} /></Card><Card title="全部门店归属"><List dataSource={e.stores ?? []} locale={{ emptyText: '不在任何门店' }} renderItem={s => <List.Item>{s.name ?? s.store_id ?? s.id}</List.Item>} /></Card></div> : null}</ResourceState></>; }

```

## frontend/src/pages/LogsPage.tsx
```
import { useState } from 'react';
import { Button, Card, DatePicker, Descriptions, Drawer, Form, Input, Select, Space, Table } from 'antd';
import type { ChangeLog } from '../domain'; import { formatTime } from '../domain'; import { query } from '../services/http'; import { useAllResource } from '../services/useAllResource'; import { PageHeader } from '../components/PageHeader'; import { ResourceState } from '../components/ResourceState';
export function LogsPage(){const [filters,setFilters]=useState<Record<string,string>>({});const [selected,setSelected]=useState<ChangeLog|null>(null);const logs=useAllResource<ChangeLog>('/admin/api/change-logs'+query({...filters,limit:100}));return <><PageHeader title="变更日志" description="按对象、操作、操作者、任务和时间查找已提交差异。"/><Card><Form layout="inline" onFinish={v=>setFilters(Object.fromEntries(Object.entries(v).filter(([,x])=>x).map(([k,x])=>[k,String(x)])))}><Form.Item name="object_id"><Input placeholder="对象 ID"/></Form.Item><Form.Item name="object_type"><Select allowClear placeholder="对象类型" style={{width:140}} options={['department','employee','store','api_client','admin'].map(v=>({value:v,label:v}))}/></Form.Item><Form.Item name="source"><Select allowClear placeholder="操作来源" style={{width:140}} options={[{value:'admin',label:'管理员'},{value:'sync',label:'飞书同步'}]}/></Form.Item><Form.Item name="actor"><Input placeholder="操作者"/></Form.Item><Form.Item name="job_id"><Input placeholder="任务 ID"/></Form.Item><Form.Item name="committed_after"><DatePicker showTime placeholder="开始时间"/></Form.Item><Form.Item><Button type="primary" htmlType="submit">查询</Button></Form.Item></Form><ResourceState {...logs} empty={!logs.data?.length}><Table className="block-gap" rowKey="id" dataSource={logs.data??[]} pagination={{pageSize:20}} scroll={{x:900}} columns={[{title:'提交时间',dataIndex:'committed_at',render:formatTime},{title:'对象',render:(_,r)=>r.object_name??`${r.object_type??''} ${r.object_id??''}`},{title:'操作',dataIndex:'action'},{title:'来源 / 操作者',render:(_,r)=>r.actor??r.actor_open_id??r.source??'—'},{title:'任务',dataIndex:'job_id',render:v=>v||'—'},{title:'操作',render:(_,r)=><Button type="link" onClick={()=>setSelected(r)}>查看差异</Button>}]} /></ResourceState></Card><Drawer title="差异详情" open={Boolean(selected)} onClose={()=>setSelected(null)} width={720}>{selected&&<><Descriptions column={1} items={[{key:'object',label:'对象',children:selected.object_name??selected.object_id},{key:'time',label:'提交时间',children:formatTime(selected.committed_at)},{key:'actor',label:'来源 / 操作者',children:selected.actor??selected.actor_open_id??selected.source??'—'}]}/><div className="diff-grid"><Card size="small" title="修改前"><pre>{JSON.stringify(selected.before,null,2)}</pre></Card><Card size="small" title="修改后"><pre>{JSON.stringify(selected.after,null,2)}</pre></Card></div></>}</Drawer></>}

```

## frontend/src/pages/OrganizationPage.tsx
```
import { useMemo, useState } from 'react';
import { Button, Card, Input, Radio, Space, Table, Tag, Tree, Typography } from 'antd';
import { EditOutlined, ShopOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { DataNode } from 'antd/es/tree';
import type { Department, Employee } from '../domain';
import { isActive } from '../domain';
import { useAllResource } from '../services/useAllResource';
import { query } from '../services/http';
import { PageHeader } from '../components/PageHeader';
import { ResourceState } from '../components/ResourceState';
import { StoreEditor } from '../components/StoreEditor';

function makeTree(items: Department[]): DataNode[] { const nodes = new Map<string, DataNode>(); items.forEach(d => nodes.set(d.id, { key: d.id, title: <span>{d.name} {d.is_store && <Tag color="blue">门店</Tag>}</span>, children: [] })); const roots: DataNode[] = []; items.forEach(d => { const n = nodes.get(d.id)!; const p = d.parent_id ? nodes.get(d.parent_id) : undefined; if (p) p.children?.push(n); else roots.push(n); }); return roots; }
export function OrganizationPage() {
  const navigate = useNavigate(); const departments = useAllResource<Department>('/admin/api/departments?include_inactive=true&limit=200');
  const [selected, setSelected] = useState<string>(); const [checked, setChecked] = useState<React.Key[]>([]); const [search, setSearch] = useState(''); const [descendants, setDescendants] = useState(false); const [editing, setEditing] = useState<Department | null>(null);
  const employees = useAllResource<Employee>(selected ? '/admin/api/employees' + query({ department_id: selected, include_descendants: descendants, limit: 200 }) : null);
  const filtered = useMemo(() => { const all = departments.data ?? []; if (!search) return all; const hits = new Set(all.filter(x => `${x.name} ${x.id}`.toLowerCase().includes(search.toLowerCase())).map(x => x.id)); return all.filter(x => hits.has(x.id) || (typeof x.path === 'string' ? [...hits].some(id => x.path!.includes(id as string)) : false)); }, [departments.data, search]);
  const current = departments.data?.find(d => d.id === selected) ?? null;
  return <><PageHeader title="组织架构" description="浏览飞书组织事实，独立选择部门并维护门店属性。" extra={<Button type="primary" disabled={!checked.length} onClick={() => setEditing(departments.data?.find(d => d.id === String(checked[0])) ?? null)}>批量设置（{checked.length}）</Button>} />
    <div className="org-grid"><Card title="部门树" extra={<Tag>{departments.data?.length ?? 0} 个部门</Tag>}><Input.Search allowClear placeholder="搜索部门名称或 ID" onSearch={setSearch} onChange={e => setSearch(e.target.value)} /><ResourceState {...departments} empty={!filtered.length}><Tree className="org-tree" blockNode checkable checkStrictly showLine defaultExpandAll treeData={makeTree(filtered)} checkedKeys={checked} selectedKeys={selected ? [selected] : []} onCheck={keys => setChecked(Array.isArray(keys) ? keys : keys.checked)} onSelect={keys => setSelected(String(keys[0] ?? ''))} /></ResourceState></Card>
      <Card title={current?.name ?? '请选择部门'} extra={current && <Button icon={<EditOutlined />} onClick={() => setEditing(current)}>编辑门店资料</Button>}><Space className="toolbar" wrap><Radio.Group value={descendants} onChange={e => setDescendants(e.target.value)} options={[{ label: '仅直属人员', value: false }, { label: '包含全部后代', value: true }]} />{current?.is_store && <Tag icon={<ShopOutlined />} color="blue">{current.store_code || '门店'}</Tag>}</Space>
        {!selected ? <Typography.Text type="secondary">从左侧选择部门以查看人员。</Typography.Text> : <ResourceState {...employees} empty={!employees.data?.length}><Table rowKey="id" dataSource={employees.data ?? []} pagination={{ pageSize: 20 }} scroll={{ x: 720 }} columns={[{ title: '姓名', dataIndex: 'name', render: (v, r) => <Button type="link" icon={<UserOutlined />} onClick={() => navigate(`/employees/${encodeURIComponent(r.id)}`)}>{v}</Button> }, { title: '员工 ID', dataIndex: 'id' }, { title: '状态', render: (_, r) => <Tag color={isActive(r) ? 'success' : 'default'}>{isActive(r) ? '在职' : '失效'}</Tag> }, { title: '主门店状态', dataIndex: 'primary_store_status' }]} /></ResourceState>}</Card></div>
    <StoreEditor department={editing} dataVersion={departments.meta.data_version} open={Boolean(editing)} onClose={() => setEditing(null)} onSaved={() => { departments.reload(); employees.reload(); }} /></>;
}

```

## frontend/src/pages/SettingsPage.tsx
```
import { useState } from 'react';
import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Space, Table, Tabs, Tag, Typography, message } from 'antd';
import type { ApiClient } from '../domain'; import { formatTime } from '../domain'; import { request } from '../services/http'; import { useAllResource } from '../services/useAllResource'; import { PageHeader } from '../components/PageHeader'; import { ResourceState } from '../components/ResourceState';
interface Admin { open_id: string; name?: string; created_at?: string }
interface Credential { client_id: string; secret: string }
export function SettingsPage(){const admins=useAllResource<Admin>('/admin/api/admin-allowlist?limit=200');const clients=useAllResource<ApiClient>('/admin/api/api-clients?limit=200');const [credential,setCredential]=useState<Credential|null>(null);const [busy,setBusy]=useState(false);async function mutate(path:string,method:string,body?:unknown,done?:()=>void){setBusy(true);try{const r=await request<Credential|Record<string,unknown>>(path,{method,body});message.success('操作已完成');const d=r.data as Partial<Credential>;if(d.client_id&&d.secret)setCredential(d as Credential);done?.();}catch(e){message.error(e instanceof Error?e.message:'操作失败');}finally{setBusy(false)}} const allowlist=<><Alert type="warning" showIcon message="移出管理员会立即撤销其所有活动会话；移除最后一名管理员也会立即生效。"/><Form className="block-gap" layout="inline" onFinish={v=>mutate('/admin/api/admin-allowlist','POST',v,admins.reload)}><Form.Item name="open_id" rules={[{required:true,message:'请输入 open_id'}]}><Input placeholder="ou_..."/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>添加管理员</Button></Form><ResourceState {...admins} empty={!admins.data?.length}><Table rowKey="open_id" dataSource={admins.data??[]} pagination={false} columns={[{title:'管理员',render:(_,r)=>r.name??r.open_id},{title:'open_id',dataIndex:'open_id'},{title:'添加时间',dataIndex:'created_at',render:formatTime},{title:'操作',render:(_,r)=><Popconfirm title="确认移出管理员白名单？" description="该管理员的活动会话会立即撤销。" onConfirm={()=>mutate(`/admin/api/admin-allowlist/${encodeURIComponent(r.open_id)}`,'DELETE',undefined,admins.reload)}><Button danger type="link">移出</Button></Popconfirm>}]} /></ResourceState></>; const clientTab=<><Alert type="info" showIcon message="每个业务系统使用独立只读凭据" description="密钥仅在创建或轮换后展示一次，请立即保存。"/><Form className="block-gap" layout="inline" onFinish={v=>mutate('/admin/api/api-clients','POST',v,clients.reload)}><Form.Item name="name" rules={[{required:true,message:'请输入使用方名称'}]}><Input placeholder="例如：薪资系统"/></Form.Item><Button type="primary" htmlType="submit" loading={busy}>创建客户端</Button></Form><ResourceState {...clients} empty={!clients.data?.length}><Table rowKey={r=>r.client_id??r.id??r.name} dataSource={clients.data??[]} pagination={false} scroll={{x:720}} columns={[{title:'使用方',dataIndex:'name'},{title:'凭据标识',render:(_,r)=>r.client_id??r.id},{title:'状态',render:(_,r)=><Tag color={r.revoked_at||r.active===false?'default':'success'}>{r.revoked_at||r.active===false?'已撤销':'启用'}</Tag>},{title:'最近调用',dataIndex:'last_used_at',render:formatTime},{title:'操作',render:(_,r)=>{const id=r.client_id??r.id;return <Space><Popconfirm title="轮换凭据？" description="旧凭据会立即失效，新密钥仅展示一次。" onConfirm={()=>mutate(`/admin/api/api-clients/${encodeURIComponent(id??'')}/rotate`,'POST',undefined,clients.reload)}><Button type="link" disabled={!id||Boolean(r.revoked_at)}>轮换</Button></Popconfirm><Popconfirm title="撤销客户端？" onConfirm={()=>mutate(`/admin/api/api-clients/${encodeURIComponent(id??'')}/revoke`,'POST',undefined,clients.reload)}><Button danger type="link" disabled={!id||Boolean(r.revoked_at)}>撤销</Button></Popconfirm></Space>}}]}/></ResourceState></>;return <><PageHeader title="管理设置" description="管理管理员资格、只读 API 客户端、连接摘要与每日核对。"/><Card><Tabs items={[{key:'connection',label:'飞书连接',children:<Alert type="info" showIcon message="后端暂未提供脱敏连接摘要接口" description="需补充只读接口后才能安全展示应用、租户与权限范围。"/>},{key:'admins',label:'管理员白名单',children:allowlist},{key:'clients',label:'API 客户端',children:clientTab},{key:'schedule',label:'每日核对',children:<Alert type="info" showIcon message="后端暂未提供每日时间读取与保存接口" description="当前不会在浏览器中模拟保存。"/>}]}/></Card><Modal title="请立即保存新凭据" open={Boolean(credential)} closable={false} mask={{closable:false}} footer={<Button type="primary" onClick={()=>setCredential(null)}>我已安全保存</Button>}><Alert type="warning" showIcon message="关闭后无法再次查看此密钥"/><Typography.Paragraph copyable className="credential"><strong>客户端：</strong>{credential?.client_id}<br/><strong>密钥：</strong>{credential?.secret}</Typography.Paragraph></Modal></>}

```

## frontend/src/pages/StoresPage.tsx
```
import { useMemo, useState } from 'react';
import { Button, Card, Drawer, Input, Radio, Space, Switch, Table, Tag } from 'antd';
import type { Employee, Store } from '../domain';
import { isActive } from '../domain';
import { useAllResource } from '../services/useAllResource';
import { query } from '../services/http';
import { PageHeader } from '../components/PageHeader'; import { ResourceState } from '../components/ResourceState'; import { StoreEditor } from '../components/StoreEditor';
export function StoresPage() { const [search, setSearch] = useState(''); const [inactive, setInactive] = useState(false); const [editing, setEditing] = useState<Store | null>(null); const [viewing, setViewing] = useState<Store | null>(null); const [membership, setMembership] = useState<'all'|'primary'>('all'); const stores = useAllResource<Store>('/admin/api/stores' + query({ include_inactive: inactive, limit: 200 })); const people = useAllResource<Employee>(viewing ? `/admin/api/stores/${encodeURIComponent(viewing.id)}/employees` + query({ membership, include_inactive: true, limit: 200 }) : null); const data = useMemo(() => (stores.data ?? []).filter(s => `${s.name} ${s.store_code ?? ''}`.toLowerCase().includes(search.toLowerCase())), [stores.data, search]); return <><PageHeader title="门店管理" description="维护门店编码和备注，并查看门店归属员工。" /><Card><Space className="toolbar" wrap><Input.Search allowClear placeholder="搜索门店名称或编码" onChange={e => setSearch(e.target.value)} /><span>包含失效门店 <Switch checked={inactive} onChange={setInactive} /></span></Space><ResourceState {...stores} empty={!data.length}><Table rowKey="id" dataSource={data} pagination={{ pageSize: 20 }} scroll={{ x: 900 }} columns={[{ title: '门店', dataIndex: 'name' }, { title: '编码', dataIndex: 'store_code', render: v => v || '—' }, { title: '路径', dataIndex: 'path', render: v => Array.isArray(v) ? v.join(' / ') : v }, { title: '全部归属人数', dataIndex: 'employee_count' }, { title: '主门店人数', dataIndex: 'primary_employee_count' }, { title: '状态', render: (_, r) => <Tag color={isActive(r) ? 'success' : 'default'}>{isActive(r) ? '有效' : '失效'}</Tag> }, { title: '操作', fixed: 'right', render: (_, r) => <Space><Button type="link" onClick={() => setViewing(r)}>查看员工</Button><Button type="link" onClick={() => setEditing(r)}>编辑</Button></Space> }]} /></ResourceState></Card><Drawer title={`${viewing?.name ?? ''} · 归属员工`} open={Boolean(viewing)} onClose={() => setViewing(null)} width={720}><Radio.Group className="toolbar" value={membership} onChange={e => setMembership(e.target.value)} options={[{ label: '全部归属', value: 'all' }, { label: '主门店归属', value: 'primary' }]} /><ResourceState {...people} empty={!people.data?.length}><Table rowKey="id" dataSource={people.data ?? []} pagination={{ pageSize: 20 }} columns={[{ title: '姓名', dataIndex: 'name' }, { title: '员工 ID', dataIndex: 'id' }, { title: '状态', render: (_, r) => isActive(r) ? '在职' : '失效' }]} /></ResourceState></Drawer><StoreEditor department={editing} dataVersion={stores.meta.data_version} open={Boolean(editing)} onClose={() => setEditing(null)} onSaved={stores.reload} /></>; }

```

## frontend/src/pages/SyncPage.tsx
```
import { useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Descriptions, Drawer, Row, Select, Space, Statistic, Table, Tag, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { SyncJob } from '../domain'; import { formatTime } from '../domain'; import { request, query } from '../services/http'; import { useResource } from '../services/useResource'; import { useAllResource } from '../services/useAllResource'; import { PageHeader } from '../components/PageHeader'; import { ResourceState } from '../components/ResourceState';
const statusMap: Record<string, { color: string; text: string }> = { queued: { color: 'default', text: '排队中' }, running: { color: 'processing', text: '执行中' }, succeeded: { color: 'success', text: '成功' }, failed: { color: 'error', text: '失败' } };
export function SyncPage() { const status = useResource<Record<string, unknown>>('/admin/api/status'); const [filter, setFilter] = useState<string>(); const jobs = useAllResource<SyncJob>('/admin/api/sync/jobs' + query({ status: filter, limit: 100 })); const [detailId, setDetailId] = useState<string>(); const detail = useResource<SyncJob>(detailId ? `/admin/api/sync/jobs/${encodeURIComponent(detailId)}` : null); const [busy, setBusy] = useState(false); useEffect(() => { if (!detailId || !detail.data || !['queued','running'].includes(detail.data.status)) return; const timer = window.setInterval(() => detail.reload(), 3000); return () => clearInterval(timer); }, [detailId, detail.data?.status, detail.reload]); async function create() { setBusy(true); try { const r = await request<{job_id:string;reused?:boolean}>('/admin/api/sync/jobs', { method:'POST', body:{type:'full'} }); message.success(r.data.reused ? '已有相同范围任务，已打开原任务' : '全量任务已创建'); setDetailId(r.data.job_id); jobs.reload(); } catch(e){ message.error(e instanceof Error ? e.message:'创建失败'); } finally { setBusy(false); } } async function retry(){ if(!detailId)return;setBusy(true);try{await request(`/admin/api/sync/jobs/${encodeURIComponent(detailId)}/retry`,{method:'POST'});message.success('重试任务已提交');detail.reload();jobs.reload();}catch(e){message.error(e instanceof Error?e.message:'重试失败');}finally{setBusy(false)}} const current=status.data??{}; return <><PageHeader title="同步中心" description="查看同步健康、实际阶段与计数；失败时保留最后成功数据。" extra={<Button type="primary" icon={<ReloadOutlined/>} loading={busy} onClick={create}>一键全量更新</Button>} /><ResourceState {...status}><Row gutter={[16,16]}><Col xs={24} md={8}><Card><Statistic title="初始化状态" value={String(current.initialized ?? current.status ?? '未知')} /></Card></Col><Col xs={24} md={8}><Card><Statistic title="覆盖状态" value={String(status.meta.coverage_status ?? current.coverage_status ?? '未知')} /></Card></Col><Col xs={24} md={8}><Card><Statistic title="最近全量成功" value={formatTime(status.meta.last_full_sync_at as string)} /></Card></Col></Row></ResourceState><Alert className="block-gap" type="info" showIcon message="连接摘要与最近事件处理时间暂无后端字段" description="页面只展示接口实际返回的信息。" /><Card title="最近任务" extra={<Select allowClear placeholder="全部状态" value={filter} onChange={setFilter} options={['queued','running','succeeded','failed'].map(v=>({value:v,label:statusMap[v].text}))}/>}><ResourceState {...jobs} empty={!jobs.data?.length}><Table rowKey={r=>r.job_id??r.id??''} dataSource={jobs.data??[]} pagination={{pageSize:20}} scroll={{x:850}} columns={[{title:'任务',render:(_,r)=>`#${r.job_id??r.id}`},{title:'类型',dataIndex:'type'},{title:'范围',dataIndex:'root_department_id',render:v=>v||'全企业'},{title:'阶段',dataIndex:'stage',render:v=>v||'—'},{title:'状态',dataIndex:'status',render:v=><Tag color={statusMap[v]?.color}>{statusMap[v]?.text??v}</Tag>},{title:'计数',render:(_,r)=>`${r.processed_department_count??0} 部门 / ${r.processed_employee_count??0} 员工${r.total_count == null?'（总量待确认）':` / ${r.total_count}`}`},{title:'创建时间',dataIndex:'created_at',render:formatTime},{title:'操作',render:(_,r)=><Button type="link" onClick={()=>setDetailId(r.job_id??r.id)}>详情</Button>}]} /></ResourceState></Card><Drawer title={`同步任务 #${detailId??''}`} open={Boolean(detailId)} onClose={()=>setDetailId(undefined)} width={560} extra={detail.data?.status==='failed'&&<Button danger loading={busy} onClick={retry}>重试</Button>}><ResourceState {...detail}>{detail.data&&<Descriptions column={1} bordered items={Object.entries(detail.data).map(([k,v])=>({key:k,label:k,children:typeof v==='object'?JSON.stringify(v):String(v??'—')}))}/>}</ResourceState></Drawer></>; }

```

## frontend/src/services/http.test.ts
```
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
});

```

## frontend/src/services/http.ts
```
export interface Meta {
  dataset_epoch?: string;
  data_version?: number;
  next_cursor?: string | null;
  coverage_status?: string;
  last_full_sync_at?: string | null;
  [key: string]: unknown;
}

export interface Envelope<T> { data: T; meta: Meta }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

let csrfToken: string | null = null;
export function setCsrfToken(value: string | null) { csrfToken = value; }

export async function request<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<Envelope<T>> {
  const method = options.method ?? 'GET';
  const headers = new Headers({ Accept: 'application/json' });
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD'].includes(method) && csrfToken) headers.set('X-CSRF-Token', csrfToken);
  let response: Response;
  try {
    response = await fetch(path, { method, headers, credentials: 'include', signal: options.signal, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查后端是否启动后重试');
  }
  let payload: unknown;
  try { payload = await response.json(); } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', '服务返回了无法识别的响应，请稍后重试');
  }
  if (!response.ok) {
    const detail = (payload as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(response.status, detail?.code ?? 'REQUEST_FAILED', detail?.message ?? '请求失败，请稍后重试');
  }
  if (typeof payload !== 'object' || payload === null || !('data' in payload)) {
    throw new ApiError(response.status, 'INVALID_RESPONSE', '响应缺少业务数据，请联系维护人员');
  }
  return payload as Envelope<T>;
}

export function query(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : '';
}

```

## frontend/src/services/readAll.test.ts
```
import { afterEach, expect, it, vi } from 'vitest';
import { readAll } from './readAll';

afterEach(() => vi.unstubAllGlobals());

it('后续分页携带首页版本，冲突后丢弃整个旧结果重读', async () => {
  const urls: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    urls.push(url);
    if (urls.length === 1) return Response.json({ data: ['old'], meta: { dataset_epoch: 'e1', data_version: 1, next_cursor: 'cursor1' } });
    if (urls.length === 2) return Response.json({ error: { code: 'DATASET_CHANGED', message: '数据变化' } }, { status: 409 });
    return Response.json({ data: ['new'], meta: { dataset_epoch: 'e1', data_version: 2, next_cursor: null } });
  });
  const result = await readAll<string>('/admin/api/departments?include_inactive=true');
  expect(result.data).toEqual(['new']);
  const second = new URL(urls[1], 'http://local');
  expect(second.searchParams.get('dataset_epoch')).toBe('e1');
  expect(second.searchParams.get('data_version')).toBe('1');
  expect(second.searchParams.get('cursor')).toBe('cursor1');
  expect(new URL(urls[2], 'http://local').searchParams.has('cursor')).toBe(false);
});

it('重复分页游标不会导致无限循环', async () => {
  vi.stubGlobal('fetch', async () => Response.json({ data: [1], meta: { dataset_epoch: 'e1', data_version: 1, next_cursor: 'same' } }));
  await expect(readAll('/items')).rejects.toMatchObject({ code: 'INVALID_PAGINATION' });
});

```

## frontend/src/services/readAll.ts
```
import { ApiError, type Envelope, type Meta, request } from './http';

/** 组织树需要完整部门集；版本冲突时整轮重读，绝不拼接两代数据。 */
export async function readAll<T>(path: string, signal?: AbortSignal): Promise<Envelope<T[]>> {
  for (let attempt = 0; attempt < 3; attempt++) {
    const data: T[] = [];
    const seen = new Set<string>();
    let meta: Meta = {};
    let cursor: string | null = null;
    try {
      do {
        const url = new URL(path, 'http://same-origin');
        if (cursor) {
          url.searchParams.set('cursor', cursor);
          if (meta.dataset_epoch) url.searchParams.set('dataset_epoch', meta.dataset_epoch);
          if (meta.data_version !== undefined) url.searchParams.set('data_version', String(meta.data_version));
        }
        const page = await request<T[]>(url.pathname + url.search, { signal });
        if (!Array.isArray(page.data)) throw new ApiError(200, 'INVALID_RESPONSE', '列表响应格式错误');
        if (cursor && (page.meta.dataset_epoch !== meta.dataset_epoch || page.meta.data_version !== meta.data_version)) {
          throw new ApiError(409, 'DATASET_CHANGED', '数据版本已更新，请重试');
        }
        data.push(...page.data);
        meta = page.meta;
        cursor = typeof meta.next_cursor === 'string' ? meta.next_cursor : null;
        if (cursor) {
          if (seen.has(cursor)) throw new ApiError(200, 'INVALID_PAGINATION', '服务返回重复分页标记，请联系维护人员');
          seen.add(cursor);
        }
      } while (cursor);
      return { data, meta };
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'DATASET_CHANGED' || attempt === 2) throw error;
    }
  }
  throw new ApiError(409, 'DATASET_CHANGED', '数据持续变化，请稍后重试');
}

```

## frontend/src/services/useAllResource.ts
```
import { useCallback, useEffect, useState } from 'react';
import { ApiError, type Meta } from './http';
import { readAll } from './readAll';

export function useAllResource<T>(path: string | null) {
  const [data, setData] = useState<T[] | null>(null);
  const [meta, setMeta] = useState<Meta>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(v => v + 1), []);
  useEffect(() => {
    const controller = new AbortController(); let current = true;
    setData(null); setMeta({}); setError(null); setLoading(Boolean(path));
    if (path) readAll<T>(path, controller.signal).then(r => { if (current) { setData(r.data); setMeta(r.meta); } }).catch(e => { if (current && e?.name !== 'AbortError') setError(e instanceof ApiError ? e : new ApiError(0, 'REQUEST_FAILED', '读取失败，请重试')); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; controller.abort(); };
  }, [path, revision]);
  return { data, meta, error, loading, reload };
}

```

## frontend/src/services/useResource.test.tsx
```
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useResource } from './useResource';

afterEach(() => vi.unstubAllGlobals());

it('快速切换部门时，较慢的旧响应不能覆盖新部门数据', async () => {
  let resolveOld!: (value: Response) => void;
  vi.stubGlobal('fetch', (path: string) => path === '/old'
    ? new Promise<Response>(resolve => { resolveOld = resolve; })
    : Promise.resolve(new Response(JSON.stringify({ data: ['new'], meta: {} }))));
  const { result, rerender } = renderHook(({ path }) => useResource<string[]>(path), { initialProps: { path: '/old' } });
  rerender({ path: '/new' });
  await waitFor(() => expect(result.current.data).toEqual(['new']));
  await act(async () => { resolveOld(new Response(JSON.stringify({ data: ['old'], meta: {} }))); });
  expect(result.current.data).toEqual(['new']);
});

it('错误后重试成功会清除旧错误', async () => {
  let fail = true;
  vi.stubGlobal('fetch', async () => fail
    ? new Response(JSON.stringify({ error: { code: 'UNAVAILABLE', message: '暂不可用' } }), { status: 503 })
    : new Response(JSON.stringify({ data: [1], meta: {} })));
  const { result } = renderHook(() => useResource<number[]>('/items'));
  await waitFor(() => expect(result.current.error?.status).toBe(503));
  fail = false;
  act(() => result.current.reload());
  await waitFor(() => expect(result.current.data).toEqual([1]));
  expect(result.current.error).toBeNull();
});

```

## frontend/src/services/useResource.ts
```
import { useCallback, useEffect, useState } from 'react';
import { ApiError, type Meta, request } from './http';

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [meta, setMeta] = useState<Meta>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setData(null);
    setMeta({});
    setError(null);
    setLoading(Boolean(path));
    if (path) {
      request<T>(path, { signal: controller.signal })
        .then(response => { if (current) { setData(response.data); setMeta(response.meta); } })
        .catch(reason => {
          if (current && reason?.name !== 'AbortError') setError(reason instanceof ApiError ? reason : new ApiError(0, 'REQUEST_FAILED', '读取失败，请重试'));
        })
        .finally(() => { if (current) setLoading(false); });
    }
    return () => { current = false; controller.abort(); };
  }, [path, revision]);

  return { data, meta, error, loading, reload };
}

```

## frontend/src/styles.css
```
*{box-sizing:border-box}body{margin:0;color:#263449;background:#f5f7fa}.app-shell{min-height:100vh}.desktop-sider{position:fixed!important;inset:0 auto 0 0;border-right:1px solid #e7eaf0;z-index:2}.desktop-sider+.ant-layout{margin-left:208px}.brand{height:64px;display:flex;align-items:center;gap:12px;padding:0 20px}.brand>span{display:grid;place-items:center;width:32px;height:32px;border-radius:8px;color:white;background:#1677ff;font-size:19px;font-weight:600}.brand div{display:flex;flex-direction:column}.brand strong{font-size:17px}.brand small,.sider-foot small{font-size:9px;letter-spacing:.08em;color:#98a2b3}.sider-foot{position:absolute;bottom:28px;left:24px;display:flex;flex-direction:column;gap:16px}.ant-layout-header{height:64px!important;background:#fff!important;border-bottom:1px solid #e7eaf0;padding:0 28px!important;display:flex;align-items:center;justify-content:space-between}.ant-layout-content{padding:28px;min-width:0}.page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:20px}.page-header h1{font-size:26px;margin:8px 0 4px;color:#172b4d}.page-header p{margin:0;color:#7b8798}.breadcrumb{font-size:12px;color:#8b96a7}.org-grid{display:grid;grid-template-columns:330px minmax(0,1fr);gap:18px}.org-tree{margin-top:16px;max-height:650px;overflow:auto}.toolbar{margin-bottom:16px}.block-gap{margin-top:16px!important}.detail-grid{display:grid;grid-template-columns:2fr 1fr;gap:16px}.detail-grid>:first-child{grid-row:span 2}.diff-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:20px}.diff-grid pre{white-space:pre-wrap;word-break:break-word;max-height:480px;overflow:auto}.credential{margin-top:18px;padding:16px;background:#f5f7fa;border-radius:8px;word-break:break-all}.mobile-menu{display:none}.ant-form-inline{gap:8px}.ant-table-wrapper{margin-top:8px}@media(max-width:900px){.desktop-sider{display:none}.desktop-sider+.ant-layout{margin-left:0}.mobile-menu{display:inline-flex}.ant-layout-content{padding:18px}.org-grid,.detail-grid,.diff-grid{grid-template-columns:1fr}.detail-grid>:first-child{grid-row:auto}.page-header{align-items:flex-start;flex-direction:column}.ant-layout-header{padding:0 18px!important}}

```

## frontend/tsconfig.json
```
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "types": ["vite/client", "vitest/globals"]
  },
  "include": ["src", "vite.config.ts"]
}

```

## frontend/vite.config.ts
```
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/admin': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  test: { environment: 'jsdom', globals: true },
});

```
