import type { ReactNode } from 'react';
import { Alert, Button, Empty, Skeleton } from 'antd';
import type { ApiError } from '../services/http';

export function ResourceState({ loading, error, empty, reload, children }: { loading: boolean; error: ApiError | null; empty?: boolean; reload: () => void; children: ReactNode }) {
  if (loading) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (error) return <Alert showIcon type="error" title={error.status === 503 ? '数据尚未就绪' : '读取失败'} description={error.message} action={<Button onClick={reload}>重试</Button>} />;
  if (empty) return <Empty description="暂无数据" />;
  return <>{children}</>;
}
