### Finding Verdicts

- **1. `coverage_invalidated` 只有置位，没有受控、可审计的恢复路径** — ADDRESSED。`backend/app/sync/coverage.py:26-45` 在同一事务锁定队列与数据状态，保存新验收依据、删除失效标记、把覆盖保持 unknown、创建验收后的 reconcile 任务并写审计；`backend/app/sync/coverage.py:48-66` 提供绑定组织校验和脱敏失败输出的 CLI。`backend/app/sync/publisher.py:77-81` 还会拒绝验收前开始的旧采集恢复 complete。报告记录针对性原子回滚、CLI 与旧候选测试通过。
- **2. OAuth 会覆盖既有 LoginIdentity 稳定映射** — ADDRESSED。`backend/app/feishu/oauth.py:37-53` 锁定既有映射并逐项核对 user_id/tenant_key；不一致时只提交固定 `LOGIN_IDENTITY_MISMATCH` 安全日志，事务提交后再拒绝登录，不修改映射、不创建会话，也不保存 code/token/secret。
- **3. 不可读的新部门被发布为虚构 active 事实** — ADDRESSED。`backend/app/sync/publisher.py:99-131` 将未闭合部门和依赖事实移入 PendingFact，不再创建 Department 占位；`backend/app/persistence/models.py:39-46` 与 `backend/migrations/versions/0003_pending_fact.py:1-16` 提供 InnoDB/utf8mb4 持久结构，worker 后续把 pending ID 纳入全量回查。已有事实只降质量并保留原关系。
- **4. 明确离职管理员的旧会话和新登录仍有效** — NOT ADDRESSED。`backend/app/sync/publisher.py:53-57,134-140` 已在普通 inactive 员工发布路径中按 LoginIdentity 撤销会话，`backend/app/persistence/repositories.py:27-36` 与 `backend/app/feishu/oauth.py:40-45` 也拒绝已持久化的明确 inactive；但 `_defer_unresolved` 在 `publisher.py:116-123` 会因为员工含不可读部门引用而把整个员工候选移出发布集合，导致第 57 行生命周期处理和撤权都不执行。根代理 SQLite 行为夹具已复现：现有 active 员工 u、`ou→u` 映射及活动 session，发布明确 `status=inactive` 且 `department_ids=['unreadable']` 的候选后，员工仍 active、session 仍未撤销。AC25 要求已确认离职立即撤权，不能依赖部门外键闭合；应保留旧资料/关系和 unknown 投影，同时独立提交可信 inactive 生命周期、撤销会话、写审计与版本更新。
- **Minor 1. 关键字段缺失错误被折叠为 `SYNC_FAILED`** — ADDRESSED。`backend/app/sync/worker.py:17`（`SAFE_SYNC_ERRORS`）及失败写回路径保留 membership/status/parent/token/detail/ID 等固定脱敏错误码；针对性测试验证 `FEISHU_PARENT_UNREADABLE` 可见。
- **Minor 2. 第三方 Starlette/AnyIO warning** — ADDRESSED AS DOCUMENTED LIMITATION。修复 brief 允许精确记录而不升级框架；`docs/superpowers/task-2-report.md` 的修复验证明确保留唯一第三方弃用 warning，没有加入宽泛过滤。它不阻塞本轮安全修复。
- **额外要求：数据库异常以及框架 404/405 返回统一、脱敏 error envelope** — ADDRESSED。`backend/app/main.py:28-44` 将 Starlette HTTPException、SQLAlchemy 数据库错误和请求校验统一为 JSON error；Operational/连接/超时类返回 503，其余数据库错误返回 500，均不输出异常、SQL 或参数。`backend/app/persistence/database.py:8-11` 启用 `hide_parameters=True`；故障注入测试覆盖敏感 SQL/参数不出现在响应及未知路由/方法 envelope。

### New Breakage in the Fix Diff

- **Important — pending 部门会阻断已确认 inactive 生命周期与原子撤权。** `backend/app/sync/publisher.py:116-123` 以任一未闭合部门引用为由延后整个 Employee，直接绕过 `publisher.py:53-65` 的员工状态更新、会话撤销和关系处理。触发方式是离职详情明确返回 resigned/exited，同时其 department_ids 中存在一个当前不可读部门；影响是已确认离职管理员继续通过旧 session 和白名单登录，恢复了原 AC25 漏洞。应拆分员工核心生命周期事实与依赖部门的关系事实：部门不可读时延后关系/主部门投影，明确 inactive 状态与撤权仍在同一发布事务完成。

### Out-of-Scope Observations

- 73 passed/6 skipped 的报告证据仍不覆盖真实 MySQL `FOR UPDATE`、迁移执行、并发撤权/发布回滚和租约语义；这些保持原未验收状态，不由本次 scoped re-review 扩展。

### Verdict

**Fix round:** Findings remain open — 原 Finding 4 / AC25 在“明确离职 + 部门引用不可读”路径仍未解决；修复差异新增同一安全回归。其余原发现和额外数据库 error envelope 已解决。

**Spec compliance:** ❌ Issues remain。

**Task quality:** Needs fixes。
