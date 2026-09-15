# Task 2：飞书接入、采集与同步执行

**Files:** `backend/app/feishu/`、`backend/app/sync/`、`backend/tests/test_feishu*.py`、`backend/tests/test_sync*.py`。

**Interfaces:** 使用 Task 1 数据模型、会话工厂、发布锁和任务表；输出 worker 可执行入口与 OAuth 回调接入。

- [ ] 查阅官方 SDK/接口，验证字段/ID 类型；写分页失败、缺失主部门、乱序事件和权限异常测试。
- [ ] 实现 OAuth code 交换与登录身份映射，state 校验、白名单校验、组织身份校验。
- [ ] 实现全量/子树分页采集、祖先补齐、事件持久化与回查、临时采集到原子发布；不可确认失效保留记录并标记质量。
- [ ] 实现单 worker 租约、退避、重启恢复、每日北京时间 03:00 核对、长连接恢复核对。
- [ ] 运行领域与适配器测试；记录真实企业授权与 MySQL 并发联调限制。

```python
# 失败采集不能覆盖旧数据。
assert after.data_version == before.data_version
assert after.employee_ids == before.employee_ids
```


## Global Constraints

## 前端与部署接续接口

- 长连接独立入口 `python -m app.feishu.listener`，部署监督 HTTP、同步 worker、listener 三个进程。SDK 1.7.3 无公开首连成功或停止 API，禁止依赖私有字段；同步回调只快速校验并持久入箱，失败不得确认成功。启动及重连安排幂等全量核对，连接状态不得把进程存活当已连接。详见契约报告第 6 节。
- 扩展 `GET /admin/api/status` 的 `data.connection={status:'connected|degraded|unconfigured',checked_at,app_id_masked,tenant_key_masked,scopes:string[]}` 与 `last_event_processed_at`；不返回 secret/token/hash，未知连接须 degraded。
- `GET /admin/api/settings/reconcile-schedule` 返回 data `{enabled:boolean,local_time:'HH:mm',timezone:'Asia/Shanghai',updated_at}`；`PUT` 同路径接受 `{enabled,local_time,timezone}`，CSRF、422 VALIDATION_ERROR、事务审计。默认每日 03:00；worker 实际使用此持久配置。
- 可扩展 backend 下必要模型、路由、依赖、迁移；现有冻结 0001 之后加新迁移。维护 `docs/backend-api.md`，报告准确运行命令及新增配置。配置缺失应明确呈现，进程不虚报同步成功。

## 已核验的飞书契约

实施前读取 `docs/superpowers/feishu-contract-check.md`。官方 SDK wheel 已在 `.cache/sdk/lark_oapi-1.7.3-py3-none-any.whl`。SDK 确认的 OIDC 登录链可直接使用；不要依赖未验证的用户访问 token 顶层结构。

- `scopes` 只有分页授权入口，没有全员覆盖布尔值。保留 `coverage_status=unknown/incomplete` 直到部署者提供配置验收证据；不得以“递归成功”等同全企业人员完整。可以发布已知的完整采集范围并显式报告覆盖不足，但不能发布失败的半次采集。
- 支持明确的部署验收配置与摘要（含无部门人员覆盖证据状态），默认未核验。不能用一个无记录的前端“全员”开关伪造覆盖。
- 状态字段继续采用既定 `active/inactive` + `sync_quality`，不要直接采用报告中概念性的三态命名以破坏接口。
- 事件租户与应用匹配、去重、必要载荷持久化；字段缺失导致不可处理时需记录可见失败，不静默丢弃。
- 详情明确失效可发布；单次详情无法读取一律保留业务事实并标记待核实，在错误码未经企业验证时不得凭猜测判定失效。
- 监督器要求 `python -m app.sync.worker` 入口。HTTP 使用 `/admin/auth/login` 与 `/admin/auth/callback`，不要另开重复 OAuth 命名空间。
- 前端会话契约：`GET /admin/auth/session` 返回 `{data:{open_id,csrf_token},meta:{}}`；`POST /admin/auth/logout` 已有，需要撤销并清理所有登录相关 Cookie。CSRF 不放 URL/query；可由受约束的同源 Cookie 在页面刷新后恢复，服务端核对与会话哈希一致，返回前端内存。回调成功跳转 `/organization`；失败给明确安全错误。
- 用户已确认先完成代码，稍后提供数据库环境；不操作 Docker 或真实企业。适配器测试使用准确样本，MySQL 并发验证保留为未执行。
- 同步发布复用/完善门店投影服务时修正两个接续问题：`StoreAdminService.preview` 当前仅按直接部门统计受影响人员，需包含后代并按实际归属变化去重（嵌套门店未受影响的关系不能误计）；重算不能把已知 `inconsistent` 主部门或不可读祖先默认为可信 `not_in_store`。请补针对性领域测试。
- `EmployeeStore.path` 当前写空数组，需填真实派生依据路径或在员工详情通过同一版本部门树提供足够路径；前端必须能解释主门店与兼职门店依据。


- 一个实例连接一个飞书组织，使用独立 MySQL；所有业务表使用 InnoDB、utf8mb4。
- 飞书事实只读，本地仅维护门店标记、编码与备注；虚拟根不能设为门店。
- 每条部门关系向上找最近门店；主门店只从唯一飞书主部门派生，未知与不在门店分开。
- 缺页、权限收窄、一次查不到不等于离职或删除；失败保留已提交版本。
- 管理员白名单与只读 API 凭据分开鉴权；秘密不回显、不写日志。
- 事实、派生、日志和版本原子提交；无业务变更不增加版本。
- 跨页/跨端点使用同一世代及版本，变化返回 409，初始化未完成返回 503。
- 中文界面；测试用例围绕行为，真实 MySQL/飞书未验证的项明确保留未验收状态。
