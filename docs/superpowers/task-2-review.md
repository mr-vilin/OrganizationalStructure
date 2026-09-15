### Spec Compliance

- ❌ Issues found：分页失败不返回候选、不可读详情保留旧事实、旧子树范围回查、单 worker 与任务双重 fence、无变化不增加版本、日志/投影/版本原子发布、OAuth state 单次消费及会话 CSRF 等主要要求均已实现；但 scope 变化后的覆盖验收没有可执行的受控恢复路径，持久登录身份映射也会被后续 OAuth 结果直接覆盖。
- ⚠️ Cannot verify from diff：报告中的 57 passed/6 skipped 证明了 SQLite 业务行为与离线适配器契约；6 项真实 MySQL 测试因没有 `ORG_TEST_DATABASE_URL` 跳过，因此 `SELECT ... FOR UPDATE`、`SKIP LOCKED`、租约接管、并发事件去重、发布/审计回滚和迁移执行仍未验收。真实飞书 OIDC 的 tenant/user 字段、通讯录覆盖、删除/离职字段、错误码、用户组 scope 与长连接重连行为也按任务约束保留未验收。

### Strengths

- `backend/app/feishu/client.py:42-62` 对所有列表强制验证 `has_more`，并拒绝缺失或重复 `page_token`；分页中途异常会直接向上传播，`backend/app/sync/collector.py:46-82` 不会返回半轮 Candidate。
- `backend/app/sync/collector.py:14-34,71-108` 对人员关系、生命周期和部门父级/生命周期缺失采取保守失败，详情不可读只进入 pending；全量和子树采集会重新查询旧范围对象与人员，避免移动出范围后遗留旧关系。
- `backend/app/sync/publisher.py:13-22` 在发布事务内同时校验全局 worker owner/generation/expiry 和任务 generation/expiry；`backend/app/sync/worker.py:102-136` 的进度、失败写回也重复执行 fence，旧 worker 无法在租约被恢复或接管后覆盖新状态。
- `backend/app/sync/publisher.py:23-90` 把暂存、事实、关系、质量降级、门店投影、变更日志、版本、任务和事件状态放在同一事务；只有 `changes` 非零才重建投影并递增版本。
- `backend/app/directory/domain.py:35-83` 将不可读祖先、缺失主部门、冲突主部门、不在门店和失效员工分开处理；`backend/app/stores/service.py:90-133` 保存实际部门到最近门店的派生路径。
- `backend/app/feishu/oauth.py:15-42` 使用随机 state 的数据库摘要、浏览器 cookie 常量时间比较、行锁和单次删除防重放，并在建立会话前验证租户、稳定 ID 和管理员白名单；会话只保存 CSRF HMAC。
- `backend/app/feishu/events.py:9-38` 校验 app/tenant/event 身份，持久化精简后的必要载荷并用事件 ID 去重；缺失对象 ID 会留下可见失败记录，不会静默确认。

### Issues

#### Critical (Must Fix)

- 无。

#### Important (Should Fix)

1. `backend/app/feishu/events.py:31-34`、`backend/app/sync/worker.py:66-67,149-150`、`backend/app/sync/publisher.py:73-75`、`docs/backend-api.md:63`：scope 更新会永久写入 `coverage_invalidated`，worker 和 publisher 只检查“该行是否存在”，仓库中没有 API、CLI 或服务方法能够在部署者重新验收后安全删除/清除它。触发方式是收到一次 `contact.scope.updated_v3`；此后即使配置中的覆盖验收重新完成、所有分页和详情成功，每次全量发布仍强制把 coverage 保持 unknown。文档称“由部署者清除此失效标记”，但没有可执行且审计的流程，覆盖状态无法恢复。应提供受管理员鉴权和 CSRF 保护的重新确认操作或明确 CLI，在同一事务记录验收依据、清除 marker、写审计并排队全量核对；仅改环境变量或手工删数据库行不足以满足可维护性和审计要求。

2. `backend/app/feishu/oauth.py:32-40`、`backend/app/persistence/models.py:22-27`：OAuth 完成时以 `open_id` 为主键直接 `db.merge(LoginIdentity(...))`，没有核对已持久映射中的 `user_id` 和 `tenant_key`。触发方式是上游异常、字段语义变化或错误响应让同一 open_id 携带不同 user_id；代码会覆盖原映射并继续为白名单 open_id 签发管理员会话，失去“稳定身份映射异常必须拒绝”的防线。应锁定既有 LoginIdentity：首次写入，后续必须三元组一致，否则拒绝登录并记录不含 token/code 的安全事件；不要覆盖既有绑定。

3. `backend/app/sync/publisher.py:29-38`：不可读的新部门会被创建为 `status='active'`、名称“待核实部门”的持久 Department。触发方式是新员工关系引用一个无权读取的祖先，或未知部门事件详情失败；数据库和读 API 中会出现由本地编造的活动飞书部门，虽然 `sync_quality` 标为 pending。影响是“飞书事实只读”和“一次查不到不等于已确认事实”边界被破坏，也会让前端把占位部门当有效部门展示。应把未解析引用保存在独立 pending/staging 结构，或让关系在祖先可确认前不进入已发布事实；若确需占位满足外键，至少必须使用明确的 unknown 生命周期且从普通部门列表默认视图隔离，不能声明 active。

4. `backend/app/sync/publisher.py:54-65`、`backend/app/persistence/repositories.py:27-35`、`backend/app/feishu/oauth.py:32-41`：同步确认 Employee 为 inactive 时只更新员工事实和关系，未通过 `LoginIdentity.user_id` 找到对应管理员并撤销 `AdminSession`；会话认证又只联接 `AdminAllowlist`，不检查员工生命周期，OAuth 登录也只检查白名单。触发方式是白名单管理员被飞书明确确认为离职但白名单记录尚未人工删除；其现有 session 仍通过每次鉴权，而且还能再次 OAuth 登录取得新 session。影响是 AC25“确认离职后撤销会话”没有实现，离职人员继续拥有管理权限。应在确认的 active→inactive 发布事务中，按 LoginIdentity.user_id 锁定对应身份并撤销全部活动会话，保证事实、日志和撤权原子提交；OAuth complete 和/或 session 鉴权还应拒绝已明确 inactive 的映射身份，同时保留不可读/待核实状态的访问，避免把权限收窄误判为离职。

#### Minor (Nice to Have)

1. `backend/app/sync/worker.py:131-135`：采集器新增的 `FEISHU_MEMBERSHIP_UNREADABLE`、`FEISHU_STATUS_UNREADABLE`、`FEISHU_PARENT_UNREADABLE` 等保守错误都会被折叠为 `SYNC_FAILED`。触发方式是飞书返回成功 HTTP 但缺少关键字段；任务列表无法区分权限/契约字段缺失和普通内部失败，降低排障可解释性。应维护一组不会含响应正文或秘密的稳定错误码映射。

2. `docs/superpowers/task-2-report.md:29-36`：全套测试仍有 1 条 Starlette/AnyIO 弃用 warning。它不是本任务逻辑失败，但 reviewer 规范要求测试输出噪声作为发现记录。可升级相容依赖或在确认第三方来源后用精确 warning filter 管理，避免掩盖新的告警。

### Assessment

**Task quality:** Needs fixes

**Reasoning:** 同步主链路的保守采集、双重租约 fence 和事务原子性设计较完整，离线行为测试也覆盖了关键失败路径；但 AC25 离职管理员撤权缺失，覆盖状态一旦失效便无法按产品流程恢复，登录身份绑定可被覆盖，且不可读部门会被发布为虚构 active 事实，因此本任务尚不能批准。
