### Finding Verdicts

- **原 Finding 4 / AC25：明确 inactive 因未解析部门而被整体延后，管理员仍可访问** — **ADDRESSED**。`backend/app/sync/publisher.py:120-130` 遇到关系字段不可读或引用部门未闭合时，仍把原候选保存为 pending；若候选的可信状态为 inactive，则同时生成 `lifecycle_only` 发布项，而不再从员工发布集合删除。`publisher.py:53-56,141-160` 独立更新已有员工为 inactive、把当前 `EmployeeDepartment` 关系置为 inactive、记录 membership 日志并撤销对应管理员会话；随后 `StoreAdminService._rebuild_projection`（第 87-90 行）清除不再有效的门店归属。最后已知姓名、来源 ID、主部门等资料不会被不完整响应覆盖。`backend/tests/test_task2_inactive_relations.py:23-35` 覆盖了原复现条件，并断言员工失效、旧关系终止、门店归属移除、会话撤销、未知部门不创建且候选保持 pending。

- **关系字段或父部门字段缺失时仍采信可信显式离职** — **ADDRESSED**。`backend/app/sync/collector.py:16-30` 先读取生命周期；只有 `is_resigned` / `is_exited` 中存在严格布尔值且至少一个为 true 时，才允许 `department_ids` 缺失并产出 `department_ids=None` 的 pending-verification inactive 候选。`collector.py:97-115` 对 None 关系安全跳过祖先解析。测试 `test_missing_membership_field_does_not_discard_explicit_inactive` 与 `test_parent_field_missing_does_not_block_user_exit` 分别覆盖关系字段缺失和关联部门父字段不可读，均验证 inactive、撤权及旧关系终止；未知部门仍未落成虚构事实。

- **请求 ID 不匹配或生命周期不是布尔值时不得撤权** — **ADDRESSED**。`backend/app/sync/collector.py:89-95` 在规范化前要求详情 `user_id` 与请求 identifier 完全一致；`collector.py:17-25` 又要求来源 ID 为非空字符串，并只接受 `type(value) is bool` 的生命周期证据。失败统一进入 pending，不生成 inactive 候选。`test_unreadable_lifecycle_or_wrong_source_id_cannot_revoke` 覆盖生命周期缺失、字符串 `"true"` 和错误来源 ID，断言员工保持 active、关系仍 active、session 未撤销。

- **关系、审计或发布失败时事实和撤权必须同事务回滚** — **ADDRESSED**。`backend/app/sync/publisher.py:12-24` 在一个 `sessions.begin()` 事务中完成 pending 分流，`publisher.py:141-170` 在相同 session 内写员工状态、关系、membership/security 日志及会话撤销，之后才重建投影、增加版本并提交。测试 `test_inactive_relations_and_revocation_roll_back_on_audit_failure` 分别向 membership/security 日志注入失败，`test_relation_write_failure_rolls_back_employee_and_sessions` 向关系更新注入失败；两者都断言员工、关系、门店归属、会话和 `data_version` 全部恢复原值。

- **新 inactive 员工的关系不完整时不得创建假部门或非法外键** — **ADDRESSED**。`publisher.py:123-134` 把未知关系和候选保存在 `PendingFact`，`publisher.py:143-150` 对不存在的员工只保存已确认 inactive 核心资料并强制 `primary_department_id=None`。`test_new_inactive_employee_with_incomplete_relations_has_no_fake_department` 断言员工可持久化，但 Department 和 EmployeeDepartment 均为空。

### New Breakage in the Fix Diff

- 本轮限定的生命周期、关系、撤权、审计和事务路径中未发现直接新破坏。

### Verification Evidence

- 实施报告记录 `backend/tests/test_task2_inactive_relations.py` 首轮 5 failed/3 passed，修复后针对性 10 passed；后端全套 83 passed、6 skipped、1 个已知第三方弃用 warning，并且 Alembic 离线生成到 0003 成功（`docs/superpowers/task-2-report.md`“修复轮 2”）。本复审按要求没有重复运行测试。
- 6 个跳过项意味着真实 MySQL 行锁、并发发布/撤权回滚和迁移执行仍未验收；SQLite 事务测试只证明当前业务事务编排，不替代 MySQL 验证。这是既有明确限制，不构成本轮 scoped 修复失败。

### Verdict

**Fix round:** All scoped findings addressed — 明确 inactive 已不依赖部门关系可读性，缺失关系/父字段仍能安全撤权；不可信生命周期和错误来源 ID 不会撤权；关系、审计、事实、投影、会话与版本保持同事务回滚；未发现直接回归。

**Spec compliance:** ✅ Compliant within the scoped R2 requirements。

**Task quality:** Approved within scope。
