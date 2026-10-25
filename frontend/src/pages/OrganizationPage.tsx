import { ResourceTable } from '../components/ResourceTable';
import { useEffect, useMemo, useRef, useState } from 'react';
import { App, Button, Card, Drawer, Input, Radio, Space, Tag, Tree, Typography } from 'antd';
import { EditOutlined, MenuOutlined, ShopOutlined, SyncOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from '@umijs/max';
import type { DataNode } from 'antd/es/tree';
import type { Department, Employee } from '../domain';
import { primaryStoreLabel, statusLabel } from '../domain';
import { useAllResource } from '../services/useAllResource';
import { query, request } from '../services/http';
import { PageHeader } from '../components/PageHeader';
import { ResourceState } from '../components/ResourceState';
import { StoreEditor } from '../components/StoreEditor';

function makeTree(items: Department[], hits: Set<string>): DataNode[] { const nodes = new Map<string, DataNode>(); items.forEach(d => nodes.set(d.id, { key: d.id, title: <span className={hits.has(d.id) ? 'tree-hit' : ''}>{d.name} {d.is_store && <Tag color="blue">门店</Tag>}</span>, children: [] })); const roots: DataNode[] = []; items.forEach(d => { const node = nodes.get(d.id)!; const parent = d.parent_id ? nodes.get(d.parent_id) : undefined; if (parent) parent.children?.push(node); else roots.push(node); }); return roots; }
function useNarrow() { return typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches; }
export function OrganizationPage() {
  const { message } = App.useApp(); const navigate = useNavigate(); const narrow = useNarrow();
  const departments = useAllResource<Department>('/admin/api/departments?include_inactive=true&limit=200');
  const [selected, setSelected] = useState<string>(); const [checked, setChecked] = useState<React.Key[]>([]); const [search, setSearch] = useState(''); const [descendants, setDescendants] = useState(false); const [editorOpen, setEditorOpen] = useState(false); const [treeOpen, setTreeOpen] = useState(false); const [syncing, setSyncing] = useState(false);
  const versionQuery = { dataset_epoch: departments.meta.dataset_epoch, data_version: departments.meta.data_version };
  const versionReady = Boolean(departments.data && departments.meta.dataset_epoch && departments.meta.data_version !== undefined);
  const rawEmployees = useAllResource<Employee>(selected && versionReady ? '/admin/api/employees' + query({ department_id: selected, include_descendants: descendants, limit: 200, ...versionQuery }) : null);
  const groupRetries = useRef(0);
  useEffect(() => { if (rawEmployees.error?.code === 'DATASET_CHANGED' && groupRetries.current < 2) { groupRetries.current += 1; departments.reload(); } }, [rawEmployees.error?.code, departments.reload]);
  useEffect(() => { if (rawEmployees.data) groupRetries.current = 0; }, [rawEmployees.data]);
  function retryGroup() { groupRetries.current = 0; departments.reload(); }
  const employees = { ...rawEmployees, reload: retryGroup };
  const { visible, hits, expanded } = useMemo(() => { const all = departments.data ?? []; if (!search) return { visible: all, hits: new Set<string>(), expanded: [] as string[] }; const matched = all.filter(d => `${d.name} ${d.id}`.toLowerCase().includes(search.toLowerCase())); const hitIds = new Set(matched.map(d => d.id)); const keep = new Set(hitIds); matched.forEach(d => { let parent = d.parent_id; while (parent) { keep.add(parent); parent = all.find(x => x.id === parent)?.parent_id ?? null; } }); return { visible: all.filter(d => keep.has(d.id)), hits: hitIds, expanded: [...keep] }; }, [departments.data, search]);
  const current = departments.data?.find(d => d.id === selected); const edited = (departments.data ?? []).filter(d => checked.map(String).includes(d.id));
  function select(keys: React.Key[]) { setSelected(keys[0] ? String(keys[0]) : undefined); if (narrow) setTreeOpen(false); }
  async function subtreeSync() { if (!selected) return; setSyncing(true); try { const r = await request<{ job_id: string; reused?: boolean }>('/admin/api/sync/jobs', { method: 'POST', body: { type: 'subtree', root_department_id: selected } }); message.success(r.data.reused ? `复用任务 #${r.data.job_id}` : `已创建任务 #${r.data.job_id}`); navigate(`/sync?job=${encodeURIComponent(r.data.job_id)}`); } catch (e) { message.error(e instanceof Error ? e.message : '创建任务失败'); } finally { setSyncing(false); } }
  const tree = <Card title="部门树" extra={<Tag>{departments.data?.length ?? 0} 个部门</Tag>}><Input.Search allowClear placeholder="搜索部门名称或 ID" value={search} onChange={e => setSearch(e.target.value)} /><ResourceState {...departments} empty={!visible.length}><Tree className="org-tree" blockNode checkable checkStrictly showLine defaultExpandAll={!search} {...(search ? { expandedKeys: expanded } : {})} treeData={makeTree(visible, hits)} checkedKeys={checked} selectedKeys={selected ? [selected] : []} onCheck={keys => setChecked(Array.isArray(keys) ? keys : keys.checked)} onSelect={select} /></ResourceState></Card>;
  return <PageHeader title="组织架构" description="浏览飞书组织事实，独立选择部门并维护门店属性。" extra={<Space wrap><Button className="tree-trigger" icon={<MenuOutlined />} onClick={() => setTreeOpen(true)}>选择部门</Button><Button type="primary" disabled={!checked.length} onClick={() => setEditorOpen(true)}>批量设置（{checked.length}）</Button></Space>}><div className="org-grid"><div className="tree-panel">{tree}</div><Card title={current?.name ?? '请选择部门'} extra={current && <Space><Button icon={<SyncOutlined />} loading={syncing} onClick={subtreeSync}>更新此部门及后代</Button><Button icon={<EditOutlined />} onClick={() => { setChecked([current.id]); setEditorOpen(true); }}>编辑门店资料</Button></Space>}><Space className="toolbar" wrap><Radio.Group value={descendants} onChange={e => setDescendants(e.target.value)} options={[{ label: '仅直属人员', value: false }, { label: '包含全部后代', value: true }]} />{current?.is_store && <Tag icon={<ShopOutlined />} color="blue">{current.store_code || '门店'}</Tag>}</Space>{!selected ? <Typography.Text type="secondary">选择部门以查看人员。</Typography.Text> : <ResourceState {...employees} empty={!employees.data?.length}><ResourceTable rowKey="id" dataSource={employees.data ?? []} pagination={{ pageSize: 20 }} scroll={{ x: 720 }} columns={[{ title: '姓名', dataIndex: 'name', render: (value, row) => <Button type="link" icon={<UserOutlined />} onClick={() => navigate(`/employees/${encodeURIComponent(row.id)}`)}>{value}</Button> }, { title: '员工 ID', dataIndex: 'id' }, { title: '状态', dataIndex: 'status', render: status => statusLabel(status) }, { title: '主门店状态', dataIndex: 'primary_store_status', render: primaryStoreLabel }]} /></ResourceState>}</Card></div><Drawer className="tree-drawer" title="选择部门" placement="left" size={360} open={treeOpen} onClose={() => setTreeOpen(false)}>{tree}</Drawer><StoreEditor departments={edited} dataVersion={departments.meta.data_version} open={editorOpen} onClose={() => setEditorOpen(false)} onConflict={departments.reload} onSaved={() => { departments.reload(); employees.reload(); }} /></PageHeader>;
}

export default OrganizationPage;
