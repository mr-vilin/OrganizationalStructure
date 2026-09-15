import { useState } from 'react';
import { Button, Card, DatePicker, Descriptions, Drawer, Form, Input, Select, Space, Table } from 'antd';
import type { Dayjs } from 'dayjs';
import type { ChangeLog } from '../domain';
import { formatTime } from '../domain';
import { query } from '../services/http';
import { useAllResource } from '../services/useAllResource';
import { PageHeader } from '../components/PageHeader';
import { ResourceState } from '../components/ResourceState';
interface FilterForm { object_id?: string; object_type?: string; action?: string; source?: string; actor?: string; job_id?: string; time?: [Dayjs, Dayjs] }
export function LogsPage() {
  const [form] = Form.useForm<FilterForm>(); const [filters, setFilters] = useState<Record<string, string>>({}); const [selected, setSelected] = useState<ChangeLog | null>(null);
  const logs = useAllResource<ChangeLog>('/admin/api/change-logs' + query({ ...filters, limit: 100 }));
  function search(values: FilterForm) { const { time, ...rest } = values; setFilters({ ...Object.fromEntries(Object.entries(rest).filter(([, value]) => value).map(([key, value]) => [key, String(value)])), ...(time ? { committed_after: time[0].toDate().toISOString(), committed_before: time[1].toDate().toISOString() } : {}) }); }
  function reset() { form.resetFields(); setFilters({}); }
  const filtersForm = <Form form={form} layout="inline" onFinish={search}>
    <Form.Item name="object_id"><Input placeholder="对象 ID" /></Form.Item>
    <Form.Item name="object_type"><Select allowClear placeholder="对象类型" style={{ width: 160 }} options={['department','employee','membership','store','api_client','admin_allowlist','event','security','settings','dataset'].map(value => ({ value, label: value }))} /></Form.Item>
    <Form.Item name="action"><Input placeholder="操作" /></Form.Item>
    <Form.Item name="source"><Select allowClear placeholder="操作来源" style={{ width: 140 }} onChange={value => form.setFieldValue('source', value)} options={[{ value:'admin', label:'管理员' }, { value:'feishu', label:'飞书同步' }]} /></Form.Item>
    <Form.Item name="actor"><Input placeholder="操作者" /></Form.Item><Form.Item name="job_id"><Input placeholder="任务 ID" /></Form.Item>
    <Form.Item name="time"><DatePicker.RangePicker showTime /></Form.Item><Form.Item><Space><Button type="primary" htmlType="submit">查询</Button><Button onClick={reset}>重置</Button></Space></Form.Item>
  </Form>;
  return <><PageHeader title="变更日志" description="按对象、操作、操作者、任务和时间查找已提交差异。" /><Card>{filtersForm}<ResourceState {...logs} empty={!logs.data?.length}><Table className="block-gap" rowKey="id" dataSource={logs.data ?? []} pagination={{ pageSize:20 }} scroll={{ x:900 }} columns={[{ title:'提交时间', dataIndex:'committed_at', render:formatTime }, { title:'对象', render:(_,row)=>row.object_name ?? `${row.object_type ?? ''} ${row.object_id ?? ''}` }, { title:'操作', dataIndex:'action' }, { title:'来源 / 操作者', render:(_,row)=>row.actor ?? row.actor_open_id ?? row.source ?? '—' }, { title:'任务', dataIndex:'job_id', render:value=>value || '—' }, { title:'操作', render:(_,row)=><Button type="link" onClick={()=>setSelected(row)}>查看差异</Button> }]} /></ResourceState></Card><Drawer title="差异详情" open={Boolean(selected)} onClose={()=>setSelected(null)} size={720}>{selected && <><Descriptions column={1} items={[{ key:'object', label:'对象', children:selected.object_name ?? selected.object_id }, { key:'time', label:'提交时间', children:formatTime(selected.committed_at) }, { key:'actor', label:'来源 / 操作者', children:selected.actor ?? selected.actor_open_id ?? selected.source ?? '—' }]} /><div className="diff-grid"><Card size="small" title="修改前"><pre>{JSON.stringify(selected.before,null,2)}</pre></Card><Card size="small" title="修改后"><pre>{JSON.stringify(selected.after,null,2)}</pre></Card></div></>}</Drawer></>;
}
