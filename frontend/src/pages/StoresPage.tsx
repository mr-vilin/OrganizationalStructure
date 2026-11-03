import { ResourceTable } from '../components/ResourceTable';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, Drawer, Input, Radio, Space, Switch, Tag } from 'antd';
import type { Employee, Store } from '../domain';
import { statusLabel } from '../domain';
import { useAllResource } from '../services/useAllResource';
import { query } from '../services/http';
import { PageHeader } from '../components/PageHeader';
import { ResourceState } from '../components/ResourceState';
import { StoreEditor } from '../components/StoreEditor';
export function StoresPage() {
  const [search, setSearch] = useState(''); const [inactive, setInactive] = useState(false); const [editing, setEditing] = useState<Store | null>(null); const [viewing, setViewing] = useState<Store | null>(null); const [membership, setMembership] = useState<'all'|'primary'>('all');
  const stores = useAllResource<Store>('/admin/api/stores' + query({ include_inactive: inactive, limit: 200 }));
  const versionReady = Boolean(stores.data && stores.meta.dataset_epoch && stores.meta.data_version !== undefined);
  const rawPeople = useAllResource<Employee>(viewing && versionReady ? `/admin/api/stores/${encodeURIComponent(viewing.id)}/employees` + query({ membership, include_inactive: true, limit: 200, dataset_epoch: stores.meta.dataset_epoch, data_version: stores.meta.data_version }) : null);
  const groupRetries = useRef(0);
  useEffect(() => { if (rawPeople.error?.code === 'DATASET_CHANGED' && groupRetries.current < 2) { groupRetries.current += 1; stores.reload(); } }, [rawPeople.error?.code, stores.reload]);
  useEffect(() => { if (rawPeople.data) groupRetries.current = 0; }, [rawPeople.data]);
  function retryGroup() { groupRetries.current = 0; stores.reload(); }
  const people = { ...rawPeople, reload: retryGroup };
  const data = useMemo(() => (stores.data ?? []).filter(s => `${s.name} ${s.store_code ?? ''}`.toLowerCase().includes(search.toLowerCase())), [stores.data, search]);
  return <PageHeader title="门店管理" description="维护门店编码和备注，并查看门店归属员工。"><Card><Space className="toolbar" wrap><Input.Search allowClear placeholder="搜索门店名称或编码" onChange={e => setSearch(e.target.value)} /><span>包含失效门店 <Switch checked={inactive} onChange={setInactive} /></span></Space><ResourceState {...stores} empty={!data.length}><ResourceTable rowKey="id" dataSource={data} pagination={{ pageSize: 20 }} scroll={{ x: 900 }} columns={[{ title: '门店', dataIndex: 'name' }, { title: '编码', dataIndex: 'store_code', render: v => v || '—' }, { title: '路径', dataIndex: 'path', render: v => v.join(' / ') }, { title: '全部归属人数', dataIndex: 'employee_count' }, { title: '主门店人数', dataIndex: 'primary_employee_count' }, { title: '状态', dataIndex: 'status', render: v => <Tag color={v === 'active' ? 'success' : v === 'inactive' ? 'default' : 'warning'}>{statusLabel(v)}</Tag> }, { title: '操作', fixed: 'right', render: (_, row) => <Space><Button type="link" onClick={() => setViewing(row)}>查看员工</Button><Button type="link" onClick={() => setEditing(row)}>编辑</Button></Space> }]} /></ResourceState></Card><Drawer title={`${viewing?.name ?? ''} · 归属员工`} open={Boolean(viewing)} onClose={() => setViewing(null)} size={720}><Radio.Group className="toolbar" value={membership} onChange={e => setMembership(e.target.value)} options={[{ label: '全部归属', value: 'all' }, { label: '主门店归属', value: 'primary' }]} /><ResourceState {...people} empty={!people.data?.length}><ResourceTable rowKey="id" dataSource={people.data ?? []} pagination={{ pageSize: 20 }} columns={[{ title: '姓名', dataIndex: 'name' }, { title: '员工 ID', dataIndex: 'id' }, { title: '状态', dataIndex: 'status', render: statusLabel }]} /></ResourceState></Drawer>{editing && <StoreEditor departments={[editing]} dataVersion={stores.meta.data_version} open onClose={() => setEditing(null)} onConflict={stores.reload} onSaved={stores.reload} />}</PageHeader>;
}

export default StoresPage;
