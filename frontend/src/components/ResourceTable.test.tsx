import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ResourceTable } from './ResourceTable';

it('保留缺少对象 ID 与空编码的业务文案，不显示 ProTable 默认占位', async () => {
  render(<ResourceTable rowKey="id" pagination={false} dataSource={[{ id: 'event', object_id: null, code: '' }]} columns={[
    { title: '对象', dataIndex: 'object_id', render: value => value ?? '缺少对象 ID' },
    { title: '编码', dataIndex: 'code', render: value => value || '未填写编码' },
  ]} />);
  expect(await screen.findByText('缺少对象 ID')).toBeTruthy();
  expect(screen.getByText('未填写编码')).toBeTruthy();
});
