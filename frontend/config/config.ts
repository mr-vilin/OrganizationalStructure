import { defineConfig } from '@umijs/max';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import routes from './routes';
import settings from './defaultSettings';

// scripts/run.mjs 在每次开发或构建时生成一次，并传给所有子进程。
const info = JSON.parse(readFileSync(process.env.ORG_BUILD_INFO_FILE!, 'utf8'));
const manifest = JSON.parse(readFileSync(resolve(__dirname, '../../version.json'), 'utf8'));
if (info.version !== manifest.version) throw new Error('构建元信息与 version.json 不一致');

export default defineConfig({
  routes,
  title: '组织服务 · 管理工作台',
  hash: true,
  publicPath: '/',
  history: { type: 'browser' },
  layout: { locale: false, ...settings },
  // 启用项目依赖解析；Provider 由 app.tsx 单一挂载，避免双重 App 上下文。
  antd: {},
  fastRefresh: true,
  utoopack: {},
  define: { __BUILD_INFO__: info },
  proxy: Object.fromEntries(['/admin', '/api', '/auth', '/health'].map(path => [path, { target: 'http://127.0.0.1:8000', changeOrigin: true }])),
});
