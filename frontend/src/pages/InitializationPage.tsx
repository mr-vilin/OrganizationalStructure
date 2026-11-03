import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Card, Form, Input, Progress, Result, Space, Spin, Steps } from 'antd';
import { CheckCircleFilled, CloseCircleFilled, LoadingOutlined } from '@ant-design/icons';
import { request } from '../services/http';

interface CheckItem { key: string; title: string; status: string; message: string }
interface Check { step: number; title: string; status: string; items: CheckItem[] }
interface Mappings { permission_role?: string; store_attribute?: string; employee_type_options?: Record<string, string> }
interface EmployeeTypeRow { id: string; name: string }
interface MappingFormValues { permission_role: string; store_attribute: string; employee_type_options: EmployeeTypeRow[] }
interface ProgressData { departments_processed?: number; employees_processed?: number; departments_total?: number | null; employees_total?: number | null }
export interface InitializationStatus {
  flow_id: string | null; phase: string; complete: boolean; checks: Check[]; checking_step?: number;
  settings: Mappings; counts?: { departments: number; employees: number };
  last_error?: { code: string; message: string; issues?: { object_id: string; field?: string; message: string }[] };
  job?: { job_id: string; status: string; phase: string; started_at?: string; updated_at?: string; finished_at?: string; progress: ProgressData } | null;
}
const titles = ['检查配置', '测试飞书连接', '试读部门与人员', '核验所需字段', '执行全量同步'];
const phases: Record<string, string> = { queued: '等待后台任务', scopes: '确认企业范围', departments: '采集部门', employees: '采集人员', collected: '完成采集', validating: '校验全量数据', publishing: '提交初始化数据', published: '初始化完成', collection_failed: '初始化失败', interrupted: '后台任务中断' };

export default function InitializationPage({ onComplete }: { onComplete?: () => void }) {
  const { message } = App.useApp();
  const [data, setData] = useState<InitializationStatus | null>(null);
  const [networkError, setNetworkError] = useState('');
  const [working, setWorking] = useState(false);
  const autoAttempt = useRef('');
  const busy = useRef(false);
  const alive = useRef(true);
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const current = ++sequence.current;
    try {
      const result = await request<InitializationStatus>('/admin/api/initialization');
      if (alive.current && current === sequence.current) { setData(result.data); setNetworkError(''); }
    } catch (error) {
      if (alive.current && current === sequence.current) setNetworkError(error instanceof Error ? error.message : '连接暂时中断');
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    void load();
    const timer = window.setInterval(() => { void load(); }, 2000);
    return () => { alive.current = false; window.clearInterval(timer); };
  }, [load]);
  const action = useCallback(async (path: string, method = 'POST', body?: unknown) => {
    if (busy.current) return;
    busy.current = true; setWorking(true);
    try {
      await request('/admin/api/initialization' + path, { method, body });
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败，请重试');
      await load();
    } finally { busy.current = false; if (alive.current) setWorking(false); }
  }, [load, message]);
  useEffect(() => {
    if (!data || data.complete || data.phase !== 'pending' || working) return;
    const step = data.checks.length + 1;
    const key = `${data.flow_id}:${step}`;
    if (step <= 4 && data.checks.every(check => check.status === 'passed') && autoAttempt.current !== key) {
      autoAttempt.current = key;
      void action(`/checks/${step}`);
    }
  }, [data, working, action]);

  if (!data) return <main className="initialization-page"><div className="initialization-shell"><Spin size="large" /><h1>正在读取初始化状态</h1>{networkError && <Alert type="warning" title={networkError} action={<Button onClick={() => void load()}>重新连接</Button>} />}</div></main>;
  const running = data.phase === 'running';
  const needsCleanup = data.phase === 'failed' || data.phase === 'cleanup_required';
  const editable = !running && !needsCleanup && !data.complete;
  const failed = data.checks.find(check => check.status === 'failed');
  const current = data.complete ? 4 : running || needsCleanup && data.phase === 'failed' ? 4 : failed ? failed.step - 1 : data.phase === 'checking' ? (data.checking_step ?? 1) - 1 : Math.min(data.checks.length, 4);
  const progress = data.job?.progress ?? {};
  const totalKnown = typeof progress.departments_total === 'number' && typeof progress.employees_total === 'number';
  const total = (progress.departments_total ?? 0) + (progress.employees_total ?? 0);
  const processed = (progress.departments_processed ?? 0) + (progress.employees_processed ?? 0);
  const elapsed = data.job?.started_at ? Math.max(0, Math.floor(((data.job.finished_at ? new Date(data.job.finished_at).getTime() : Date.now()) - new Date(data.job.started_at).getTime()) / 1000)) : 0;
  const enter = onComplete ?? (() => window.location.assign('/organization'));
  return <main className="initialization-page"><div className="initialization-shell">
    <header className="initialization-header"><div><span className="initialization-eyebrow">组织服务 · 管理员初始化</span><h1>准备好企业组织数据</h1><p>逐项完成检查，再同步企业的全部部门与人员。</p></div><Button onClick={async () => { await request('/admin/auth/logout', { method: 'POST' }); window.location.reload(); }}>退出登录</Button></header>
    <Steps current={current} items={titles.map((title, index) => ({ title, status: data.complete ? 'finish' : index === 4 ? data.phase === 'failed' ? 'error' : running ? 'process' : 'wait' : data.checks.find(check => check.step === index + 1)?.status === 'passed' ? 'finish' : failed?.step === index + 1 ? 'error' : current === index ? 'process' : 'wait' }))} />
    {networkError && <Alert type="warning" showIcon title="连接暂时中断，正在重新连接" description={networkError} />}
    {data.complete ? <Result status="success" title="初始化完成" subTitle={`已同步 ${data.counts?.departments ?? 0} 个部门、${data.counts?.employees ?? 0} 位人员，全部校验通过。`} extra={<Button type="primary" onClick={enter}>进入系统</Button>} /> : <>
      {needsCleanup && <Alert type={data.phase === 'failed' ? 'error' : 'warning'} showIcon title={data.phase === 'failed' ? '本轮初始化未成功' : '需要按新流程重新初始化'} description={<><p>{data.last_error?.message ?? '现有实例需要重新完成初始化。'}</p><p>重新开始会清除部门、人员、关系、门店资料（含编码、备注）及临时采集结果，保留飞书配置、管理员资格、登录能力和失败审计。</p></>} action={<Button danger loading={working} onClick={() => { autoAttempt.current = ''; void action('/restart'); }}>{data.phase === 'failed' ? '重新开始' : '重新初始化'}</Button>} />}
      {data.last_error?.issues?.length ? <Card title="需要修正的数据"><ul className="initialization-issues">{data.last_error.issues.map((issue, index) => <li key={index}><strong>{issue.object_id}</strong> {issue.field}：{issue.message}</li>)}</ul></Card> : null}
      {data.phase === 'ready' && <Card className="initialization-ready" title="所有前置检查已通过"><p>开始后将读取全企业数据，逐条校验并提交。后台任务中断后需要从头重来。</p><Button type="primary" size="large" loading={working} onClick={() => void action('/start')}>立即同步</Button></Card>}
      {data.job && <Card title={phases[data.job.phase] ?? '初始化同步进度'}><Space wrap><strong>已采集部门：{progress.departments_processed ?? 0}{typeof progress.departments_total === 'number' ? ` / ${progress.departments_total}` : ''}</strong><strong>已采集人员：{progress.employees_processed ?? 0}{typeof progress.employees_total === 'number' ? ` / ${progress.employees_total}` : ''}</strong><span>耗时 {elapsed} 秒</span></Space>{totalKnown && total > 0 ? <><p>采集进度</p><Progress percent={Math.round(processed / total * 100)} status={data.phase === 'failed' ? 'exception' : 'active'} /></> : running && <p><Spin size="small" /> 正在发现和读取数据…</p>}{data.job.updated_at && <p className="initialization-muted">最近更新：{new Date(data.job.updated_at).toLocaleString()}</p>}</Card>}
      <section className="initialization-checks" aria-label="初始化检查清单">{titles.slice(0, 4).map((title, index) => {
        const check = data.checks.find(item => item.step === index + 1);
        const checking = data.phase === 'checking' && data.checking_step === index + 1;
        return <Card key={title} title={<Space>{check?.status === 'passed' ? <CheckCircleFilled className="check-passed" /> : check?.status === 'failed' ? <CloseCircleFilled className="check-failed" /> : checking ? <LoadingOutlined spin /> : <span className="check-pending">{index + 1}</span>}{title}</Space>} extra={check?.status === 'passed' ? '已通过' : checking ? '检查中' : check?.status === 'failed' ? '未通过' : '待检查'}>
          {check?.items ? <ul className="check-items">{check.items.map(item => <li key={item.key}>{item.status === 'passed' ? <CheckCircleFilled className="check-passed" /> : <CloseCircleFilled className="check-failed" />}<div><strong>{item.title}</strong>{item.message && <p>{item.message}</p>}</div></li>)}</ul> : <p className="initialization-muted">{checking ? '正在验证，请稍候…' : '按顺序完成前置检查。'}</p>}
          {editable && check?.status === 'failed' && <Button loading={working} onClick={() => { autoAttempt.current = ''; void action(`/checks/${index + 1}`); }}>重新检测</Button>}
        </Card>;
      })}</section>
      {editable && <Card title="修正字段映射" extra="仅维护非敏感设置"><Form<MappingFormValues> key={`${data.flow_id}:settings`} name="initialization-settings" initialValues={{ ...data.settings, employee_type_options: Object.entries(data.settings.employee_type_options ?? {}).map(([id, name]) => ({ id, name })) }} layout="vertical" disabled={working || data.phase === 'checking'} onFinish={async values => {
        const options = Object.fromEntries(values.employee_type_options.map(row => [row.id.trim(), row.name.trim()]));
        autoAttempt.current = '';
        await action('/settings', 'PUT', { permission_role: values.permission_role, store_attribute: values.store_attribute, employee_type_options: options });
      }}>
        <div className="initialization-form-grid"><Form.Item name="permission_role" label="权限角色字段 ID" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="store_attribute" label="门店属性字段 ID" rules={[{ required: true }]}><Input /></Form.Item></div>
        <section className="initialization-options" aria-labelledby="employee-type-options-title">
          <h3 id="employee-type-options-title">员工类型选项</h3>
          <p className="initialization-muted">每行填写一个选项的 ID 和名称。</p>
          <Form.List name="employee_type_options">
            {(fields, { add, remove }) => <>
              {fields.length === 0 && <p className="initialization-muted">暂未配置员工类型选项，点击“新增一行”开始填写。</p>}
              {fields.map(field => <div className="initialization-option-row" key={field.key}>
                <Form.Item name={[field.name, 'id']} label="选项 ID" dependencies={['employee_type_options']} rules={[
                  { required: true, whitespace: true, message: '请填写选项 ID' },
                  ({ getFieldValue }) => ({ validator: async (_, value?: string) => {
                    const rows: EmployeeTypeRow[] = getFieldValue('employee_type_options') ?? [];
                    if (value?.trim() && rows.filter(row => row?.id?.trim() === value.trim()).length > 1) throw new Error('选项 ID 不能重复');
                  } }),
                ]}><Input /></Form.Item>
                <Form.Item name={[field.name, 'name']} label="选项名称" rules={[{ required: true, whitespace: true, message: '请填写选项名称' }]}><Input /></Form.Item>
                <Button danger className="initialization-option-remove" aria-label={`删除第 ${field.name + 1} 行`} onClick={() => remove(field.name)}>删除</Button>
              </div>)}
              <Button type="dashed" onClick={() => add({ id: '', name: '' })}>新增一行</Button>
            </>}
          </Form.List>
        </section>
        <Button htmlType="submit" loading={working}>保存设置并重新检查</Button>
      </Form></Card>}

    </>}
  </div></main>;
}
