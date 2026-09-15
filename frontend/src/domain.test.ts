import { describe, expect, it } from 'vitest';
import { primaryStoreLabel, previewMatches } from './domain';

describe('管理端领域规则', () => {
  it('只有预览版本和当前版本一致时才允许提交', () => {
    expect(previewMatches({ dataVersion: 42, fingerprint: 'a' }, 42, 'a')).toBe(true);
    expect(previewMatches({ dataVersion: 42, fingerprint: 'a' }, 43, 'a')).toBe(false);
    expect(previewMatches({ dataVersion: 42, fingerprint: 'a' }, 42, 'b')).toBe(false);
  });

  it('区分未归属门店与无法判断', () => {
    expect(primaryStoreLabel('not_in_store')).toBe('不在门店');
    expect(primaryStoreLabel('unknown')).toBe('暂无法判断');
  });
});
