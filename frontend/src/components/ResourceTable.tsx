import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import type { TableProps } from 'antd';

function adaptColumns<T extends object>(columns: NonNullable<TableProps<T>['columns']>): ProColumns<T>[] {
  return columns.map(column => {
    if ('children' in column) return { ...column, children: adaptColumns(column.children) } as ProColumns<T>;
    const render = column.render;
    if (!render) return column as ProColumns<T>;
    return {
      ...column,
      // Pro 的 render 参数已经过占位转换；原业务回调继续接收原始字段值。
      render: (_value, row, index) => {
        const path = column.dataIndex === undefined ? [] : Array.isArray(column.dataIndex) ? column.dataIndex : [column.dataIndex];
        const value = path.reduce<unknown>((current, key) => current == null ? undefined : (current as Record<PropertyKey, unknown>)[key as PropertyKey], row);
        return render(value, row, index);
      },
    } as ProColumns<T>;
  });
}

// 资源 hooks 是唯一读取来源；不向 ProTable 暴露自动 request 或后端页码。
export function ResourceTable<T extends object>(props: TableProps<T>) {
  return <ProTable<T>
    {...props}
    columns={adaptColumns(props.columns ?? [])}
    rowSelection={props.rowSelection ?? false}
    search={false}
    options={false}
    toolBarRender={false}
    cardProps={false}
    dateFormatter={false}
  />;
}
