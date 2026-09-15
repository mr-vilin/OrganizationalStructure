import { useCallback, useEffect, useState } from 'react';
import { ApiError, type Meta } from './http';
import { readAll } from './readAll';

export function useAllResource<T>(path: string | null) {
  const [data, setData] = useState<T[] | null>(null);
  const [meta, setMeta] = useState<Meta>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(v => v + 1), []);
  useEffect(() => {
    const controller = new AbortController(); let current = true;
    setData(null); setMeta({}); setError(null); setLoading(Boolean(path));
    if (path) readAll<T>(path, controller.signal).then(r => { if (current) { setData(r.data); setMeta(r.meta); } }).catch(e => { if (current && e?.name !== 'AbortError') setError(e instanceof ApiError ? e : new ApiError(0, 'REQUEST_FAILED', '读取失败，请重试')); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; controller.abort(); };
  }, [path, revision]);
  return { data, meta, error, loading, reload };
}
