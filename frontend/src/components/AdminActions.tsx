import { LogoutOutlined, UserOutlined } from '@ant-design/icons';
import { App, Button, Popover, Space, Typography } from 'antd';
import { request } from '../services/http';
import { useAdminSession } from './AuthGate';

export function AdminActions() {
  const session = useAdminSession();
  const { message } = App.useApp();
  async function logout() {
    try {
      await request('/admin/auth/logout', { method: 'POST' });
      location.assign('/');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '退出失败');
    }
  }
  return <Space wrap>
    <Popover title="当前管理员" content={<Typography.Text copyable>{session?.open_id}</Typography.Text>} trigger="click">
      <Button type="text" icon={<UserOutlined />}>管理员</Button>
    </Popover>
    <Button type="text" icon={<LogoutOutlined />} onClick={logout}>退出</Button>
  </Space>;
}
