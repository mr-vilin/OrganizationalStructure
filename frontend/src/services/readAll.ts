import { ApiError, type Envelope, type Meta, request } from './http';

/** 组织树需要完整部门集；版本冲突时整轮重读，绝不拼接两代数据。 */
export async function readAll<T>(path: string, signal?: AbortSignal): Promise<Envelope<T[]>> {
  const initialUrl = new URL(path, 'http://same-origin');
  const externallyBound = initialUrl.searchParams.has('dataset_epoch') || initialUrl.searchParams.has('data_version');
  for (let attempt = 0; attempt < 3; attempt++) {
    const data: T[] = [];
    const seen = new Set<string>();
    let meta: Meta = {};
    let cursor: string | null = null;
    try {
      do {
        const url = new URL(path, 'http://same-origin');
        if (cursor) {
          url.searchParams.set('cursor', cursor);
          if (meta.dataset_epoch) url.searchParams.set('dataset_epoch', meta.dataset_epoch);
          if (meta.data_version !== undefined) url.searchParams.set('data_version', String(meta.data_version));
        }
        const page = await request<T[]>(url.pathname + url.search, { signal });
        if (!Array.isArray(page.data)) throw new ApiError(200, 'INVALID_RESPONSE', '列表响应格式错误');
        if (cursor && (page.meta.dataset_epoch !== meta.dataset_epoch || page.meta.data_version !== meta.data_version)) {
          throw new ApiError(409, 'DATASET_CHANGED', '数据版本已更新，请重试');
        }
        data.push(...page.data);
        meta = page.meta;
        cursor = typeof meta.next_cursor === 'string' ? meta.next_cursor : null;
        if (cursor) {
          if (seen.has(cursor)) throw new ApiError(200, 'INVALID_PAGINATION', '服务返回重复分页标记，请联系维护人员');
          seen.add(cursor);
        }
      } while (cursor);
      return { data, meta };
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'DATASET_CHANGED' || externallyBound || attempt === 2) throw error;
    }
  }
  throw new ApiError(409, 'DATASET_CHANGED', '数据持续变化，请稍后重试');
}
