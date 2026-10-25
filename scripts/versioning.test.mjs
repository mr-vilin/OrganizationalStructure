import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { parseVersion, compareVersions, releaseRecords, checkIncrement, checkRepository, buildInfo } from './versioning.mjs';

function fixture(t, version = '0.1.0', entries = '') {
  const root = mkdtempSync(join(tmpdir(), 'organization-version-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  writeFileSync(join(root, 'version.json'), JSON.stringify({ version }));
  writeFileSync(join(root, 'CHANGELOG.md'), `# 产品版本\n\n## [Unreleased]\n\n开发改动\n\n${entries}`);
  return root;
}

test('遵循官方预发布优先级，编译信息不影响排序，大整数不丢失精度', () => {
  const versions = ['1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0'];
  for (let i = 1; i < versions.length; i++) assert.equal(compareVersions(versions[i - 1], versions[i]), -1);
  assert.equal(compareVersions('1.0.0+001', '1.0.0+sha.abc'), 0);
  assert.equal(compareVersions('1.0.0-9007199254740992', '1.0.0-9007199254740993'), -1);
});

test('拒绝前导零、v 前缀和无效标识，允许合法构建信息', () => {
  for (const value of ['v0.1.0', '0.1', '01.1.0', '0.01.0', '0.1.00', '0.1.0-01', '0.1.0-', '0.1.0+']) assert.throws(() => parseVersion(value));
  for (const value of ['0.1.0', '0.1.0-alpha.1', '0.1.0-01a', '0.1.0+001']) assert.doesNotThrow(() => parseVersion(value));
});

test('同日可有多个版本，但拒绝重复版本、非法日期和日期乱序', () => {
  const header = '## [Unreleased]\n\n';
  assert.equal(releaseRecords(header + '## [0.1.1] — 2026-10-24\n修复\n## [0.1.0] — 2026-10-24\n初始').length, 2);
  for (const entries of [
    '## [0.1.0] — 2026-10-24\n## [0.1.0] — 2026-10-23',
    '## [0.1.0] — 2026-02-30',
    '## [0.1.1] — 2026-10-23\n## [0.1.0] — 2026-10-24',
    '## [0.1.0] — 2026-10-24\n## [Unreleased]',
  ]) assert.throws(() => releaseRecords(header + entries));
});

test('升级必须清零低位，预发布可以晋升正式版本，禁止构建信息冒充新版本', () => {
  for (const [a, b] of [['0.1.3', '0.2.0'], ['1.4.3', '2.0.0'], ['1.4.3', '1.5.0-rc.1'], ['1.5.0-rc.1', '1.5.0']]) assert.doesNotThrow(() => checkIncrement(a, b));
  for (const [a, b] of [['1.4.3', '1.5.4'], ['1.4.3', '2.1.0'], ['1.4.3', '1.4.2'], ['1.4.3', '1.4.5'], ['1.4.3', '1.4.3+build.2']]) assert.throws(() => checkIncrement(a, b));
});

test('开发基线和已准备的发布记录都不会把普通构建误标为已发布', t => {
  const root = fixture(t);
  assert.equal(checkRepository(root).version, '0.1.0');
  assert.throws(() => checkRepository(root, { release: true }), /最新版本记录/);
  writeFileSync(join(root, 'CHANGELOG.md'), '## [Unreleased]\n## [0.1.0] — 2026-10-24\n初始');
  const info = buildInfo(root, {});
  assert.equal(info.stage, 'development');
  assert.equal(info.releaseDate, null);
  assert.equal(info.commit, 'unknown');
  assert.equal(info.dirty, null);
});

test('发行产物要求 tag、版本记录、提交和干净源码状态一致', t => {
  const root = fixture(t, '0.1.0-rc.1', '## [0.1.0-rc.1] — 2026-10-24\n候选');
  assert.throws(() => checkRepository(root, { tag: 'v0.1.0' }), /tag/);
  const env = { ORG_RELEASE_TAG: 'v0.1.0-rc.1', ORG_COMMIT_SHA: 'a'.repeat(40), ORG_SOURCE_DIRTY: 'false' };
  const info = buildInfo(root, env);
  assert.equal(info.stage, 'prerelease');
  assert.equal(info.releaseDate, '2026-10-24');
  assert.throws(() => buildInfo(root, { ...env, ORG_SOURCE_DIRTY: 'true' }), /干净/);
  assert.throws(() => buildInfo(root, { ...env, ORG_COMMIT_SHA: 'unknown' }), /真实提交/);
});

test('PR 基准检查拒绝改写已有发行说明或降低版本', t => {
  const root = fixture(t, '0.1.0', '## [0.1.0] — 2026-10-24\n原始说明\n');
  const run = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  run(['init', '--quiet']);
  run(['add', '.']);
  run(['-c', 'user.name=Version Test', '-c', 'user.email=version-test@example.invalid', 'commit', '--quiet', '-m', 'fixture']);
  const baseRef = run(['rev-parse', 'HEAD']);
  assert.doesNotThrow(() => checkRepository(root, { baseRef }));
  run(['tag', 'v0.1.0']);
  assert.doesNotThrow(() => checkRepository(root, { tag: 'v0.1.0' }));
  writeFileSync(join(root, 'CHANGELOG.md'), '## [Unreleased]\n## [0.1.0] — 2026-10-24\n改写说明\n');
  assert.throws(() => checkRepository(root, { baseRef }), /不得修改/);
  assert.throws(() => checkRepository(root, { tag: 'v0.1.0' }), /干净/);
  writeFileSync(join(root, 'version.json'), JSON.stringify({ version: '0.0.9' }));
  assert.throws(() => checkRepository(root, { baseRef }), /低于/);
});
