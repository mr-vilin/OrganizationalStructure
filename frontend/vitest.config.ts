import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { buildInfo, repositoryRoot } from '../scripts/versioning.mjs';

const info = process.env.ORG_BUILD_INFO_FILE
  ? JSON.parse(readFileSync(process.env.ORG_BUILD_INFO_FILE, 'utf8'))
  : buildInfo(repositoryRoot);
const manifest = JSON.parse(readFileSync(`${repositoryRoot}/version.json`, 'utf8'));
if (info.version !== manifest.version) throw new Error('构建元信息与 version.json 不一致');

export default defineConfig({
  resolve: { alias: {
    '@umijs/max': fileURLToPath(new URL('./src/test/router.ts', import.meta.url)),
    '@ant-design/pro-components': fileURLToPath(new URL('./node_modules/@ant-design/pro-components/es/index.js', import.meta.url)),
  } },
  plugins: [react()],
  define: { __BUILD_INFO__: JSON.stringify(info) },
  test: { environment: 'jsdom', globals: true, testTimeout: 60000, setupFiles: ['./src/test/setup.ts'], server: { deps: { inline: [/antd/, /@ant-design\//] } } },
});
