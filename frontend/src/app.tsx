import type { ReactNode } from 'react';
import type { RunTimeLayoutConfig } from '@umijs/max';
import { Link } from '@umijs/max';
import { Tag } from 'antd';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import { Providers } from './components/Providers';
import { PageErrorBoundary } from './components/PageErrorBoundary';
import settings from '../config/defaultSettings';
import './styles.css';
import './responsive.css';

export function rootContainer(container: ReactNode) {
  return <Providers>{container}</Providers>;
}

export const layout: RunTimeLayoutConfig = () => ({
  ...settings,
  ErrorBoundary: PageErrorBoundary,
  headerRender: (props) => <WorkspaceHeader collapsed={props.collapsed} onCollapse={props.onCollapse} />,
  collapsedButtonRender: false,
  menuExtraRender: ({ collapsed, isMobile }) => collapsed && !isMobile ? null : <div className="instance-label"><strong>组织服务</strong><Tag>单企业实例</Tag></div>,
  menuItemRender: (item, dom) => item.path ? <Link to={item.path} onClick={item.isMobile ? item.onClick : undefined}>{dom}</Link> : dom,
  menuFooterRender: () => <span>内部管理工作台</span>,
  links: [],
  footerRender: false,
  breadcrumbRender: false,
});
