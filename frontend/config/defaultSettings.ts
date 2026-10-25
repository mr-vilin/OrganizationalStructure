import type { ProLayoutProps } from '@ant-design/pro-components';

const settings: ProLayoutProps = {
  title: '组织服务',
  // Pro 3 的 side 模式在桌面隐藏页头；mix + splitMenus=false 保留完整侧栏和顶栏。
  layout: 'mix',
  splitMenus: false,
  navTheme: 'light',
  contentWidth: 'Fluid',
  fixedHeader: true,
  fixSiderbar: true,
  siderWidth: 208,
  logo: false,
  colorPrimary: '#1677ff',
};
export default settings;
