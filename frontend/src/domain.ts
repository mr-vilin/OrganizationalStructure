export type PrimaryStoreStatus = 'resolved' | 'not_in_store' | 'unknown' | 'inconsistent' | 'inactive';
export type RecordStatus = 'active' | 'inactive';
export interface Department { id: string; name: string; parent_id: string | null; path: string[]; status: RecordStatus; sync_quality?: string; is_virtual_root: boolean; leader_user_id?: string | null; leader_name?: string | null; is_store: boolean; store_code: string | null; notes: string | null; employee_count?: number }
export interface Employee { id: string; name: string; employee_no?: string | null; status: RecordStatus; sync_quality?: string; employee_type_id?: string | null; employee_type_name?: string | null; job_title?: string | null; leader_user_id?: string | null; leader_name?: string | null; permission_role_id?: string | null; permission_role_name?: string | null; store_attribute_id?: string | null; store_attribute_name?: string | null; department_ids: string[]; departments: Department[]; primary_department_id: string | null; stores: Array<{ id: string; name: string; is_primary: boolean; path: string[]; path_names: string[] }>; store_ids: string[]; primary_store_id: string | null; primary_store_status: PrimaryStoreStatus }
export interface Store extends Department { employee_count?: number; primary_employee_count?: number }
export interface SyncJobDetail { id?: number; object_type: string; object_id: string; object_name?: string | null; status: string; error_code?: string | null; error_message?: string | null; attempt?: number; started_at?: string | null; finished_at?: string | null; change_log_id?: number | null }
export interface SyncJob { id?: string; job_id?: string; type: string; status: string; stage?: string; phase?: string; root_department_id?: string | null; attempt_count?: number; attempt?: number; execution_count?: number; retry_count?: number; created_at?: string; updated_at?: string; error_code?: string | null; processed_department_count?: number; processed_employee_count?: number; total_count?: number | null; success_count?: number; failure_count?: number; details?: SyncJobDetail[]; [key: string]: unknown }
export interface ChangeLog { id: string | number; object_type?: string; object_id?: string; object_name?: string; action?: string; source?: string; actor?: string; actor_open_id?: string; job_id?: string; committed_at?: string; before?: unknown; after?: unknown }
export interface ApiClient { id?: string; client_id?: string; name: string; revoked_at?: string | null; active?: boolean; last_used_at?: string | null }
export interface PreviewToken { dataVersion: number; fingerprint: string }
export interface StoreChange { department_id: string; is_store: boolean; store_code?: string | null; notes?: string | null }

export function stableFingerprint(value: unknown) { return JSON.stringify(value); }
export function previewMatches(token: PreviewToken | null, dataVersion: number | undefined, fingerprint: string) { return Boolean(token && dataVersion !== undefined && token.dataVersion === dataVersion && token.fingerprint === fingerprint); }
export function primaryStoreLabel(status?: PrimaryStoreStatus) {
  return ({ resolved: '已解析', not_in_store: '不在门店', unknown: '暂无法判断', inconsistent: '数据不一致', inactive: '员工已失效' } as Record<string, string>)[status ?? ''] ?? '暂无法判断';
}
export function statusLabel(status?: RecordStatus) { return status === 'active' ? '有效' : status === 'inactive' ? '失效' : '未知'; }
export function isActive(value: { status?: RecordStatus }) { return value.status === 'active'; }
export function formatTime(value?: string | null) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' }).format(date); }
