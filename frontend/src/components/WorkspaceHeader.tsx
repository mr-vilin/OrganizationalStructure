import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { AdminActions } from './AdminActions';

export function WorkspaceHeader({ collapsed, onCollapse }: { collapsed?: boolean; onCollapse?: (collapsed: boolean) => void }) {
  return <header className="workspace-header">
    <div className="workspace-title"><Button type="text" aria-label={collapsed ? '展开导航' : '收起导航'} aria-expanded={!collapsed} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => onCollapse?.(!collapsed)} /><strong>组织管理工作台</strong></div>
    <AdminActions />
  </header>;
}
