import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildInfo, repositoryRoot } from '../../scripts/versioning.mjs';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const command = process.argv[2];
const info = process.env.ORG_BUILD_INFO_FILE
  ? JSON.parse(readFileSync(process.env.ORG_BUILD_INFO_FILE, 'utf8'))
  : buildInfo(repositoryRoot);
const infoFile = resolve(frontend, `.cache/build-info-${command}.json`);
mkdirSync(dirname(infoFile), { recursive: true });
writeFileSync(infoFile, JSON.stringify(info, null, 2) + '\n');
const env = { ...process.env, ORG_BUILD_INFO_FILE: infoFile, PORT: process.env.PORT || '5173', HOST: process.env.HOST || '127.0.0.1' };

function run(binary, args) {
  const result = spawnSync(process.execPath, [resolve(frontend, binary), ...args], { cwd: frontend, env, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
const max = 'node_modules/@umijs/max/bin/max.js';
if (['build', 'typecheck'].includes(command)) {
  run(max, ['setup']);
  run('node_modules/typescript/bin/tsc', ['--noEmit']);
}
if (command === 'build') {
  run(max, ['build']);
  writeFileSync(resolve(frontend, 'dist/build-info.json'), JSON.stringify(info, null, 2) + '\n');
} else if (command === 'typecheck') {
  // 类型检查已在上面完成。
} else if (['dev', 'setup'].includes(command)) {
  run(max, [command]);
} else {
  throw new Error(`不支持的前端命令：${command}`);
}
