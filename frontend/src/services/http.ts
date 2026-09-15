export interface Meta {
  dataset_epoch?: string;
  data_version?: number;
  next_cursor?: string | null;
  coverage_status?: string;
  last_full_sync_at?: string | null;
  [key: string]: unknown;
}

export interface Envelope<T> { data: T; meta: Meta }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

let csrfToken: string | null = null;
export function setCsrfToken(value: string | null) { csrfToken = value; }
export const AUTH_FAILURE_EVENT = 'org-admin-auth-failure';

export async function request<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<Envelope<T>> {
  const method = options.method ?? 'GET';
  const headers = new Headers({ Accept: 'application/json' });
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD'].includes(method) && csrfToken) headers.set('X-CSRF-Token', csrfToken);
  let response: Response;
  try {
    response = await fetch(path, { method, headers, credentials: 'include', signal: options.signal, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务，请检查后端是否启动后重试');
  }
  let payload: unknown;
  try { payload = await response.json(); } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', '服务返回了无法识别的响应，请稍后重试');
  }
  if (!response.ok) {
    const detail = (payload as { error?: { code?: string; message?: string } } | null)?.error;
    if ((response.status === 401 || response.status === 403) && path !== '/admin/auth/session') {
      csrfToken = null;
      window.dispatchEvent(new CustomEvent(AUTH_FAILURE_EVENT, { detail: { status: response.status } }));
    }
    throw new ApiError(response.status, detail?.code ?? 'REQUEST_FAILED', detail?.message ?? '请求失败，请稍后重试');
  }
  if (typeof payload !== 'object' || payload === null || !('data' in payload)) {
    throw new ApiError(response.status, 'INVALID_RESPONSE', '响应缺少业务数据，请联系维护人员');
  }
  return payload as Envelope<T>;
}

export function query(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : '';
}
