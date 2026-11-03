/** 产品版本与构建元信息工具；只使用 Node.js 标准库。 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

export const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const number = '(0|[1-9][0-9]*)';
const identifier = '(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)';
const semver = new RegExp(`^${number}\\.${number}\\.${number}(?:-(${identifier}(?:\\.${identifier})*))?(?:\\+([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?$`);

export function parseVersion(value) {
  const match = typeof value === 'string' && semver.exec(value);
  if (!match) throw new Error(`不是合法的 SemVer 版本：${value}`);
  return { core: match.slice(1, 4).map(BigInt), pre: match[4]?.split('.') ?? [] };
}

export function compareVersions(left, right) {
  const a = parseVersion(left), b = parseVersion(right);
  for (let i = 0; i < 3; i++) {
    if (a.core[i] !== b.core[i]) return a.core[i] > b.core[i] ? 1 : -1;
  }
  if (!a.pre.length || !b.pre.length) return a.pre.length === b.pre.length ? 0 : a.pre.length ? -1 : 1;
  for (let i = 0; i < Math.max(a.pre.length, b.pre.length); i++) {
    const x = a.pre[i], y = b.pre[i];
    if (x === y) continue;
    if (x === undefined || y === undefined) return x === undefined ? -1 : 1;
    const nx = /^\d+$/.test(x), ny = /^\d+$/.test(y);
    if (nx && ny) return BigInt(x) > BigInt(y) ? 1 : -1;
    if (nx !== ny) return nx ? -1 : 1;
    return x > y ? 1 : -1;
  }
  return 0;
}

export function releaseRecords(markdown) {
  const sections = markdown.replace(/\r\n/g, '\n').split(/^## /m).slice(1);
  const seen = new Set();
  const records = [];
  let unreleased = 0;
  for (const section of sections) {
    const [heading] = section.split('\n');
    if (heading === '[Unreleased]') {
      if (++unreleased > 1 || records.length) throw new Error('Unreleased 必须唯一且位于版本记录之前');
      continue;
    }
    if (!heading.startsWith('[')) continue;
    const match = /^\[([^\]]+)\] — (\d{4}-\d{2}-\d{2})$/.exec(heading);
    if (!match) throw new Error(`版本记录标题格式错误：${heading}`);
    const [, version, date] = match;
    parseVersion(version);
    const parsed = new Date(`${date}T00:00:00Z`);
    if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== date) throw new Error(`发布日期无效：${date}`);
    if (seen.has(version)) throw new Error(`重复版本：${version}`);
    if (records.length && records.at(-1).date < date) throw new Error('发布记录必须按日期倒序排列');
    seen.add(version);
    records.push({ version, date, text: section.trimEnd() });
  }
  if (unreleased !== 1) throw new Error('必须保留一个 Unreleased 开发记录区');
  return records;
}

export function checkIncrement(previous, next) {
  if (compareVersions(next, previous) <= 0) throw new Error('新发布版本必须高于前一个版本，构建信息不计入优先级');
  const a = parseVersion(previous), b = parseVersion(next);
  const [x, y, z] = a.core, [nx, ny, nz] = b.core;
  if (x === nx && y === ny && z === nz && a.pre.length) return;
  if (nx === x + 1n && ny === 0n && nz === 0n) return;
  if (nx === x && ny === y + 1n && nz === 0n) return;
  if (nx === x && ny === y && nz === z + 1n) return;
  throw new Error('版本递增不符合规则：major/minor 必须清零低位，且每批只递增一级');
}

function git(root, args) {
  try { return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim(); }
  catch { return null; }
}

export function checkRepository(root = repositoryRoot, { release = false, tag, baseRef } = {}) {
  const manifest = JSON.parse(readFileSync(resolve(root, 'version.json'), 'utf8'));
  if (Object.keys(manifest).join(',') !== 'version') throw new Error('version.json 只允许 version 字段');
  const { version } = manifest;
  parseVersion(version);
  const records = releaseRecords(readFileSync(resolve(root, 'CHANGELOG.md'), 'utf8'));
  for (let i = 0; i < records.length - 1; i++) checkIncrement(records[i + 1].version, records[i].version);
  if (records[0] && compareVersions(version, records[0].version) < 0) throw new Error('当前版本低于最新记录');
  if (baseRef) {
    if (!/^[0-9a-f]{40}$/.test(baseRef)) throw new Error('base-ref 必须是完整提交 SHA');
    const oldChangelog = git(root, ['show', `${baseRef}:CHANGELOG.md`]);
    if (oldChangelog === null) throw new Error('无法读取基准提交的 CHANGELOG.md');
    // 旧规则台账没有方括号标题；首次重编号经 ADR 0003 明确授权。
    if (oldChangelog.includes('## [Unreleased]')) {
      for (const record of releaseRecords(oldChangelog)) {
        if (!records.some(item => item.version === record.version && item.text === record.text)) throw new Error(`不得修改或移除既有版本记录：${record.version}`);
      }
      const oldManifest = git(root, ['show', `${baseRef}:version.json`]);
      if (oldManifest === null) throw new Error('无法读取基准提交的 version.json');
      const oldVersion = JSON.parse(oldManifest).version;
      if (oldVersion !== version) checkIncrement(oldVersion, version);
    }
  }
  if (release || tag) {
    if (records[0]?.version !== version) throw new Error('发布时 version.json 必须对应最新版本记录');
    if (tag && tag !== `v${version}`) throw new Error('tag 与 version.json 不一致');
    const head = git(root, ['rev-parse', 'HEAD']);
    if (tag && head) {
      if (git(root, ['rev-parse', '--verify', `refs/tags/${tag}^{commit}`]) !== head) throw new Error('发布 tag 必须指向当前提交');
      if (git(root, ['status', '--porcelain']) !== '') throw new Error('发布构建要求干净工作区');
    }
  }
  return { version, records };
}

export function buildInfo(root = repositoryRoot, env = process.env) {
  const tag = env.ORG_RELEASE_TAG || undefined;
  const { version, records } = checkRepository(root, { tag });
  const head = git(root, ['rev-parse', 'HEAD']);
  const commit = env.ORG_COMMIT_SHA || head || 'unknown';
  if (commit !== 'unknown' && !/^[0-9a-f]{40}$/.test(commit)) throw new Error('提交标识必须是完整 Git SHA');
  if (head && env.ORG_COMMIT_SHA && commit !== head) throw new Error('构建提交与当前 Git HEAD 不一致');
  const status = git(root, ['status', '--porcelain']);
  if (env.ORG_SOURCE_DIRTY && !['true', 'false'].includes(env.ORG_SOURCE_DIRTY)) throw new Error('ORG_SOURCE_DIRTY 只允许 true/false');
  const dirty = status === null ? (env.ORG_SOURCE_DIRTY ? env.ORG_SOURCE_DIRTY === 'true' : null) : status !== '';
  if (tag && (commit === 'unknown' || dirty !== false)) throw new Error('发布构建必须提供真实提交及干净源代码状态');
  return {
    version, commit, dirty, builtAt: new Date().toISOString(),
    stage: tag ? (parseVersion(version).pre.length ? 'prerelease' : 'release') : 'development',
    releaseDate: tag ? records[0].date : null,
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [command, ...args] = process.argv.slice(2);
    const option = name => {
      const at = args.indexOf(name);
      if (at !== -1 && (!args[at + 1] || args[at + 1].startsWith('--'))) throw new Error(`${name} 缺少参数`);
      return at === -1 ? undefined : args[at + 1];
    };
    const options = { release: args.includes('--release'), tag: option('--tag') || process.env.ORG_RELEASE_TAG || undefined, baseRef: option('--base-ref') };
    if (command === 'check') {
      const result = checkRepository(repositoryRoot, options);
      console.log(`版本校验通过：${result.version}，${result.records.length} 条发行记录`);
    } else if (command === 'build-info') {
      checkRepository(repositoryRoot, options);
      const output = option('--output');
      if (!output) throw new Error('build-info 需要 --output 文件路径');
      const result = buildInfo(repositoryRoot, { ...process.env, ORG_RELEASE_TAG: options.tag });
      writeFileSync(resolve(output), JSON.stringify(result, null, 2) + '\n');
      console.log(`构建元信息已生成：${result.version}（${result.stage}）`);
    } else throw new Error('用法：node scripts/versioning.mjs check [--release] [--tag vX.Y.Z] [--base-ref SHA] 或 build-info --output 路径');
  } catch (error) {
    console.error(`版本校验失败：${error.message}`);
    process.exitCode = 1;
  }
}
