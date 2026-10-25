import type { ReactNode } from 'react';
import { App, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { AuthGate } from './AuthGate';

export function Providers({ children }: { children: ReactNode }) {
  return <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#1677ff', borderRadius: 8, colorBgLayout: '#f5f7fa', fontFamily: 'Microsoft YaHei, PingFang SC, system-ui, sans-serif' } }}>
    <App><AuthGate>{children}</AuthGate></App>
  </ConfigProvider>;
}
