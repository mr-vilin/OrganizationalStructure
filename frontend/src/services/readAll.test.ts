import { afterEach, expect, it, vi } from 'vitest';
import { readAll } from './readAll';

afterEach(() => vi.unstubAllGlobals());

it('后续分页携带首页版本，冲突后丢弃整个旧结果重读', async () => {
  const urls: string[] = [];
  vi.stubGlobal('fetch', async (url: string) => {
    urls.push(url);
    if (urls.length === 1) return Response.json({ data: ['old'], meta: { dataset_epoch: 'e1', data_version: 1, next_cursor: 'cursor1' } });
    if (urls.length === 2) return Response.json({ error: { code: 'DATASET_CHANGED', message: '数据变化' } }, { status: 409 });
    return Response.json({ data: ['new'], meta: { dataset_epoch: 'e1', data_version: 2, next_cursor: null } });
  });
  const result = await readAll<string>('/admin/api/departments?include_inactive=true');
  expect(result.data).toEqual(['new']);
  const second = new URL(urls[1], 'http://local');
  expect(second.searchParams.get('dataset_epoch')).toBe('e1');
  expect(second.searchParams.get('data_version')).toBe('1');
  expect(second.searchParams.get('cursor')).toBe('cursor1');
  expect(new URL(urls[2], 'http://local').searchParams.has('cursor')).toBe(false);
});

it('重复分页游标不会导致无限循环', async () => {
  vi.stubGlobal('fetch', async () => Response.json({ data: [1], meta: { dataset_epoch: 'e1', data_version: 1, next_cursor: 'same' } }));
  await expect(readAll('/items')).rejects.toMatchObject({ code: 'INVALID_PAGINATION' });
});
it('外部固定版本冲突时立即交给父子协调层，不重复旧基准', async () => {
  const fetcher=vi.fn(async()=>Response.json({error:{code:'DATASET_CHANGED',message:'changed'}},{status:409})); vi.stubGlobal('fetch',fetcher); await expect(readAll('/admin/api/employees?dataset_epoch=e&data_version=1')).rejects.toMatchObject({code:'DATASET_CHANGED'}); expect(fetcher).toHaveBeenCalledOnce();
});
