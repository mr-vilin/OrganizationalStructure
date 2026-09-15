# 后端 API 契约

本契约供管理前端、飞书适配器和只读下游共同使用。所有成功响应使用 `{"data": ..., "meta": ...}`，失败响应使用 `{"error":{"code":"...","message":"..."}}`。日期时间均为 UTC ISO 8601；来源 ID 区分大小写。

## 鉴权

- `/api/v1/**`：`Authorization: Bearer <client_id>.<secret>`。密钥创建或轮换时只返回一次，数据库仅保存哈希。
- `/admin/api/**`：`org_session` HttpOnly 会话 Cookie。所有写请求还必须带 `X-CSRF-Token`。
- `GET /admin/auth/login`：创建十分钟一次性持久 state 并 302 跳转飞书 OIDC 授权入口；身份配置缺失时返回 `503 IDENTITY_NOT_CONFIGURED`。
- `GET /admin/auth/callback?code=&state=`：校验 state 与浏览器 Cookie、兑换应用身份 OIDC token、读取用户身份并核对租户和管理员白名单。成功设置 Secure/HttpOnly 会话及 CSRF Cookie，302 跳转 `/organization`；CSRF 不进入 URL。
- `GET /admin/auth/session`：返回 `{data:{open_id,csrf_token},meta:{}}`，必须携带有效会话与匹配服务端会话哈希的 `org_csrf` Cookie，响应 `Cache-Control: no-store`。Cookie 仅 `/admin/auth` 路径、SameSite=Strict、HttpOnly；前端读取此接口恢复内存中的令牌。
- `POST /admin/auth/logout`：校验 CSRF 后撤销会话并清理 `org_session/org_csrf/org_oauth_state`。
- 数据库首次使用时绑定 `FeishuConnection(app_id,tenant_key)`；之后更换应用或租户复用该数据库将返回 `503 CONFIG_BINDING_MISMATCH`，worker/listener 同样拒绝启动，不覆盖原绑定。
- `LoginIdentity(open_id,user_id,tenant_key)` 首次绑定后不可覆盖。后续映射不一致拒绝登录，返回 `LOGIN_IDENTITY_MISMATCH`，安全审计独立提交且只记录固定错误码。明确 inactive 员工拒绝新 OAuth 登录（`EMPLOYEE_INACTIVE`）；其已有会话在同步发布事务中全部撤销，会话鉴权也实时检查明确 inactive。pending/unreadable 不视为离职，白名单不因该流程被自动删除。
- 管理员身份每次请求查询数据库白名单。删除白名单或撤销会话后立即失效；机器凭据不能调用管理接口。

## 公共读取

| 方法 | 路径 | 参数与返回 |
| --- | --- | --- |
| GET | `/api/v1/status` | 初始化状态、覆盖状态；`meta` 含世代、版本及最近全量成功时间 |
| GET | `/api/v1/departments` | `parent_id`、`root_id`、`include_descendants`、`include_inactive`、`limit`、`cursor`、`dataset_epoch`、`data_version` |
| GET | `/api/v1/departments/{id}` | 已知失效部门仍返回；未知 ID 返回 404 |
| GET | `/api/v1/employees` | `department_id`、`include_descendants`、`store_id`、`primary_store_id`、`include_inactive` 及分页版本参数 |
| GET | `/api/v1/employees/{id}` | 部门关系、全部门店、主门店和 `primary_store_status` |
| GET | `/api/v1/stores` | `include_inactive` 及分页版本参数 |
| GET | `/api/v1/stores/{id}` | 当前或历史门店资料；未知 ID 返回 404 |
| GET | `/api/v1/stores/{id}/employees` | `membership=all|primary`、`include_inactive`、`cursor`、`dataset_epoch`、`data_version` |

列表 `data` 为数组。`meta` 结构：

```json
{
  "dataset_epoch": "EpochA",
  "data_version": 42,
  "coverage_status": "complete",
  "last_full_sync_at": "2026-09-15T02:00:00Z",
  "next_cursor": "opaque-or-null"
}
```

跨端点或跨页拉取应把首页的 `dataset_epoch` 与 `data_version` 传给后续请求。版本变化返回 `409 DATASET_CHANGED`；尚无成功版本返回 `503 INITIALIZATION_INCOMPLETE`。

员工的 `primary_store_status`：`resolved`、`not_in_store`、`unknown`、`inconsistent`、`inactive`。数组顺序不表达主归属。

## 管理端

### 同步任务

- `POST /admin/api/sync/jobs`：`{"type":"full|subtree|reconcile","root_department_id":"..."}`，返回 202。相同活动范围返回原 `job_id` 且 `reused=true`。
- `GET /admin/api/sync/jobs/{job_id}`：返回 `phase/status/attempt/error_code` 与 `progress={phase,departments_processed,employees_processed,departments_total,employees_total}`。未开始的计数和未知总量为 null；采集中的已处理数量来自真实候选记录，不能据此伪造百分比。阶段为 `scopes/departments/employees/collected/published/collection_failed`，后台持续持久更新。
- `POST /admin/api/sync/jobs/{job_id}/retry`：仅失败任务可重试，返回 202；其他状态返回 409。

worker 通过 `SqlSyncJobRepository.claim_next()` 认领任务；全局租约、任务租约世代与发布事务防止过期 worker 覆盖数据。失败采集最多自动执行五次，间隔从 30 秒开始指数退避；达到上限后可由管理接口重试。所有全量任务均回查旧对象，子树任务也回查先前子树内已移动对象；缺失或不可读的详情保留旧事实并标记 `pending_verification`，不猜测离职或删除。

- `GET /admin/api/sync/events?status=&limit=&cursor=`：事件可见性接口，返回 `event_id/event_type/object_id/status/attempts/received_at/error_code`，不返回原始载荷。事件按 ID 稳定分页。
- `POST /admin/api/sync/events/{event_id}/retry`：CSRF 保护；有对象 ID 的失败事件重新排队，返回 202 并事务审计；缺失对象 ID 或非失败状态返回 `409 EVENT_NOT_RETRYABLE`。字段缺失事件和待核实事件不会静默丢弃。
- 事件处理每次回查当前详情，迟到删除事件不能覆盖已恢复的有效详情。详情不可读时保留业务事实；事件标 failed 并显示 `PENDING_VERIFICATION`，可重试，日核对仍会回查旧记录。

### 连接与每日核对

- `GET /admin/api/status` 即使初始化未完成也提供管理诊断。`data.connection={status:'connected|degraded|unconfigured',checked_at,app_id_masked,tenant_key_masked,scopes:string[]}`；`last_event_processed_at` 为最近成功处理事务的 UTC 时间，`failed_event_count` 为失败事件数。
- 首连无公开确认通知，因此初始状态 degraded；合法事件入箱或 SDK 公开重连成功 hook 提供最近连接证据。90 秒无新证据时退回 degraded，不能把进程存活当 connected。`scopes` 是部署者声明的已授权 scope 名称，不能当作接口验证过的权限清单。
- `data.coverage_acceptance={reference,all_members_verified,departmentless_verified}` 表示部署验收配置；默认未核验。有持久重新验收记录时优先返回该记录，另含 `accepted_by/updated_at`。只有两项验收及非空依据、根与全部分页/详情成功且无用户组未解析范围才允许 complete。scope 变化事件立即把覆盖降为 unknown，并持久设置 `coverage_invalidated`。重新验收通过下述 CLI 完成；不手工删除数据库标记，不进行缺席失效推断。
- `GET /admin/api/settings/reconcile-schedule` 返回 `{data:{enabled,local_time,timezone,updated_at},meta:{}}`。默认 `true/03:00/Asia/Shanghai/null`。
- `PUT` 同路径接受 `{enabled:boolean,local_time:'HH:mm',timezone:'Asia/Shanghai'}`，须 CSRF；无效参数返回 `422 VALIDATION_ERROR`，设置与审计同事务。worker 实际读取此配置，日任务与北京时间日期去重标记在同一事务持久化。启动与长连接恢复均安排幂等全量核对。

覆盖重新验收由具备部署主机及数据库配置权限的运维人员在 `backend` 目录执行：

```powershell
./.venv/Scripts/python.exe -m app.sync.coverage --reference "企业验收记录-2026-09-15-02" --actor "operator:运维人员" --all-members-verified --departmentless-verified
```

执行前须核验已发布应用的全部成员权限、无部门员工覆盖并准备真实验收依据；不要在 reference 中填写 secret/token。CLI 校验数据库组织绑定，在同一事务保存依据、清除失效标记、记录审计并新建 reconcile 任务，返回 `job_id/status=queued`。覆盖仍为 unknown，只有重新验收之后开始的完整采集才可恢复 complete；旧的在途采集不能恢复。worker 每轮读取持久记录，无需重启才能生效。

未解析的新部门及依赖它的新事实保存在内部 `pending_fact`，不向部门/员工正常列表发布虚构 active 占位。已有事实和关系原样保留、质量降为 pending；新祖先缺失时主门店为 unknown。后续全量任务回查这些稳定来源 ID，详情明确后再原子发布并清理 pending。未解析候选永远不等于离职或删除。

可信离职生命周期与部门关系完整性分开处理：详情来源 ID 匹配且 `is_resigned/is_exited` 明确为布尔 true 时，即使部门关系字段缺失或新部门/父链不可读，仍发布 inactive、结束全部当前活动关系/门店归属并撤销关联管理员会话，以上与日志及版本同事务。已有员工保留最后已知姓名、来源 ID 与历史部门关系；未解析的新关系留在 pending。新员工仅保存已确认的身份资料和 inactive，缺失部门不造假。生命周期缺失、字符串 true、请求 ID 不符或详情失败都不能推断离职。

部门详情 ID 匹配且 `is_deleted` 明确为布尔 true 时，已有部门删除同样独立于父引用可读性发布；父引用缺失或未知时保留最后已知名称/父引用，并保留未解析候选。删除同事务结束该部门直接当前人员关系，其他兼职关系、员工本人状态及管理员会话不变；不级联推断子部门删除。门店派生及展示依据遇 inactive 节点停止，不能越过旧父链。后续员工详情引用已删除部门不能重新激活该关系；须先明确恢复部门、再取得可信员工关系回查才恢复。未知新部门的父引用不可读时继续隔离，不能编造根部门关系。

### 门店

- `POST /admin/api/stores/batch/preview`：请求为 `{"data_version":42,"changes":[{"department_id":"DepA","is_store":true,"store_code":"A-01","notes":"..."}]}`。返回规范化 changes 与 `affected_employee_count`。
- `POST /admin/api/stores/batch/apply`：请求同 preview；在锁定版本的事务中保存门店资料、编码保留、员工门店投影、变更日志并递增版本。没有业务变化时版本不递增。
- `PATCH /admin/api/stores/{store_id}?data_version=42`：body 为单项 change；路径 ID 必须与 `department_id` 相同。

仅 `is_store`、`store_code`、`notes` 可写。编码会去除首尾空格，空串转为 null；编码按大小写敏感方式永久保留给原部门。虚拟根和失效部门不能新设为门店。preview 后版本变化时 apply 返回 409。

### 日志与安全设置

- `GET /admin/api/change-logs`：参数 `object_type/object_id/source/job_id/actor/action/committed_after/committed_before/limit` 与数字文本 `cursor`。响应 `meta.next_cursor` 统一为 `string|null`，后续请求可直接传回；不返回 JSON 数字游标。`action=create|update|delete` 根据 before/after 是否为空分类；事实从 active 改 inactive 仍为 update。时间必须带时区，转换为 UTC 后按包含边界过滤；返回 before/after、action、actor、job_id 和 committed_at。
- `GET /admin/api/admin-allowlist`；`POST /admin/api/admin-allowlist` body `{"open_id":"ou_..."}`；`DELETE /admin/api/admin-allowlist/{open_id}`。删除会在同一事务撤销该身份的活动会话，删除最后一名也立即生效。添加、删除与脱敏日志同事务提交。
- `GET /admin/api/api-clients`；`POST /admin/api/api-clients` body `{"name":"薪资系统"}`；`POST /admin/api/api-clients/{client_id}/rotate`；`POST /admin/api/api-clients/{client_id}/revoke`。创建与轮换响应包含一次性的 `secret`；列表、后续查询和日志不返回 secret 或哈希。轮换在一个事务中锁定并撤销旧凭据、创建新凭据和写审计，任一步失败整笔回滚。

管理页面读取使用 `/admin/api/status`、`/admin/api/departments[/{id}]`、`/admin/api/employees[/{id}]`、`/admin/api/stores[/{id}]`、`/admin/api/stores/{id}/employees`，参数和响应字段与同名公共接口一致。部门含 `path/is_store/store_code`；员工含部门关系和主门店解析状态；门店含 `path/employee_count/primary_employee_count`。同步任务列表为 `GET /admin/api/sync/jobs?status=&limit=&cursor=`，按 `(created_at,id)` 倒序稳定分页；读取任务无需 CSRF。

部门另含 `notes`，供编辑保留原备注。员工保留 `department_ids/store_ids/primary_department_id/primary_store_id`，并增加 `departments`（完整部门展示字段，path 为根到部门的名称数组）和 `stores=[{id,name,is_primary,path,path_names}]`。门店 `path` 为员工所属部门向上至最近门店的 ID 数组，`path_names` 为对应名称；主门店优先展示主部门的派生路径。所有这些依据在同一数据版本事务内读取。

门店 PATCH 中省略 `store_code` 或 `notes` 表示保留原值，显式 `null` 表示清空该字段。`is_store=false` 始终保留历史编码和备注。

所有响应时间均明确序列化为 UTC（ISO 8601 `+00:00`，与 `Z` 等价）；浏览器再按北京时间展示。

## 健康检查

- `GET /health/live`：无任何业务配置也返回 200，用于进程存活检查。
- `GET /health/ready`：验证数据库连接；未配置返回 `503 DATABASE_NOT_CONFIGURED`，不可达返回 `503 DATABASE_UNAVAILABLE`。初始化状态由 `/api/v1/status` 表达，不阻止 HTTP 进程启动。

## 常用错误码

| HTTP | code | 含义 |
| --- | --- | --- |
| 401 | `UNAUTHORIZED` / `ADMIN_SESSION_REQUIRED` | API 凭据无效或缺少管理员会话 |
| 403 | `CSRF_REQUIRED` | 管理写请求缺少或使用无效 CSRF |
| 404 | `*_NOT_FOUND` | 稳定 ID 从未出现 |
| 409 | `DATASET_CHANGED` | 世代或版本变化，整轮重试 |
| 409 | `JOB_NOT_RETRYABLE` | 任务当前不能重试 |
| 422 | `VALIDATION_ERROR` / `INVALID_JOB_SCOPE` | 参数或任务范围无效 |
| 503 | `INITIALIZATION_INCOMPLETE` | 尚无可用已提交数据版本 |
| 503 | `DATABASE_UNAVAILABLE` | 数据库连接、操作或超时故障；统一 JSON 响应，不含 SQL 或参数 |
| 500 | `DATABASE_ERROR` | 其他数据库操作异常；统一 JSON 响应 |

框架未知路由 404、方法不允许 405 同样返回 `error` JSON envelope。生产 SQLAlchemy engine 启用 `hide_parameters=True`；数据库异常处理器不输出异常原文、SQL 参数或连接信息。
