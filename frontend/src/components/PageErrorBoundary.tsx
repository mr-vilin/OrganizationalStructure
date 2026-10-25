import { Component, type ReactNode } from 'react';
import { Button, Result, Space } from 'antd';
import { useLocation } from '@umijs/max';

class RenderBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <Result status="warning" title="页面暂时无法加载" subTitle="页面资源可能已经更新，请刷新后重试。" extra={<Space wrap>
      <Button type="primary" onClick={() => window.location.reload()}>刷新页面</Button>
      <Button href="/organization">返回组织架构</Button>
    </Space>} />;
  }
}

function BoundaryWithLocation({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <RenderBoundary key={location.pathname}>{children}</RenderBoundary>;
}

// ProLayout 的 ErrorBoundary 接口要求类组件；路由 hook 在内部适配。
export class PageErrorBoundary extends Component<{ children: ReactNode }> {
  render() { return <BoundaryWithLocation>{this.props.children}</BoundaryWithLocation>; }
}
