import { useCallback, useEffect, useState } from 'react';
import { ApiError, type Meta, request } from './http';

export function useResource<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [meta, setMeta] = useState<Meta>({});
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setData(null);
    setMeta({});
    setError(null);
    setLoading(Boolean(path));
    if (path) {
      request<T>(path, { signal: controller.signal })
        .then(response => { if (current) { setData(response.data); setMeta(response.meta); } })
        .catch(reason => {
          if (current && reason?.name !== 'AbortError') setError(reason instanceof ApiError ? reason : new ApiError(0, 'REQUEST_FAILED', '读取失败，请重试'));
        })
        .finally(() => { if (current) setLoading(false); });
    }
    return () => { current = false; controller.abort(); };
  }, [path, revision]);

  return { data, meta, error, loading, reload };
}
