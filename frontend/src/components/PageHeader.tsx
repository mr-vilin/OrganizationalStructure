import type { ReactNode } from 'react';
import { PageContainer } from '@ant-design/pro-components';

export function PageHeader({ title, description, extra, children }: { title: string; description: string; extra?: ReactNode; children?: ReactNode }) {
  return <PageContainer className="page-heading" ghost title={<h1>{title}</h1>} content={description} extra={extra} breadcrumb={{ items: [{ title: '工作台' }, { title }] }}>{children}</PageContainer>;
}
