import { useState } from 'react';
import { ApartmentOutlined, AuditOutlined, InfoCircleOutlined, LogoutOutlined, MenuOutlined, SettingOutlined, ShopOutlined, SyncOutlined } from '@ant-design/icons';
import { App as AntApp, Button, Drawer, Layout, Menu, Space, Tag, Typography } from 'antd';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { request } from './services/http';
import { OrganizationPage } from './pages/OrganizationPage';
import { EmployeePage } from './pages/EmployeePage';
import { StoresPage } from './pages/StoresPage';
import { SyncPage } from './pages/SyncPage';
import { LogsPage } from './pages/LogsPage';
import { SettingsPage } from './pages/SettingsPage';
import { SystemInfoPage } from './pages/SystemInfoPage';

const items = [
  { key: '/organization', icon: <ApartmentOutlined />, label: '组织架构' },
  { key: '/stores', icon: <ShopOutlined />, label: '门店管理' },
  { key: '/sync', icon: <SyncOutlined />, label: '同步中心' },
  { key: '/logs', icon: <AuditOutlined />, label: '变更日志' },
  { key: '/settings', icon: <SettingOutlined />, label: '管理设置' },
  { key: '/system-info', icon: <InfoCircleOutlined />, label: '系统信息' },
];

function Navigation() {
  const nav = useNavigate();
  const loc = useLocation();
  return <Menu mode="inline" selectedKeys={[items.find((item) => loc.pathname.startsWith(item.key))?.key ?? '/organization']} items={items} onClick={(event) => nav(event.key)} />;
}

export function App() {
  const [mobile, setMobile] = useState(false);
  const { message } = AntApp.useApp();
  async function logout() {
    try { await request('/admin/auth/logout', { method: 'POST' }); location.assign('/'); }
    catch (error) { message.error(error instanceof Error ? error.message : '退出失败'); }
  }
  return <Layout className="app-shell">
    <Layout.Sider className="desktop-sider" width={208} theme="light"><div className="brand"><span>组</span><div><strong>组织服务</strong><small>ORGANIZATION</small></div></div><Navigation/><div className="sider-foot"><Tag>单企业实例</Tag><small>内部管理工作台</small></div></Layout.Sider>
    <Layout><Layout.Header><Button className="mobile-menu" icon={<MenuOutlined />} onClick={() => setMobile(true)} /><Typography.Text strong>组织管理工作台</Typography.Text><Space><Tag color="blue">管理员</Tag><Button type="text" icon={<LogoutOutlined />} onClick={logout}>退出</Button></Space></Layout.Header>
      <Layout.Content><Routes><Route path="/organization" element={<OrganizationPage />} /><Route path="/employees/:id" element={<EmployeePage />} /><Route path="/stores" element={<StoresPage />} /><Route path="/sync" element={<SyncPage />} /><Route path="/logs" element={<LogsPage />} /><Route path="/settings" element={<SettingsPage />} /><Route path="/system-info" element={<SystemInfoPage />} /><Route path="*" element={<Navigate to="/organization" replace />} /></Routes></Layout.Content>
    </Layout>
    <Drawer title="组织服务" placement="left" size={240} open={mobile} onClose={() => setMobile(false)}><Navigation /></Drawer>
  </Layout>;
}
