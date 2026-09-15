# Task 1 限定复审（修复轮 1）

### Spec Compliance

- ✅ 原审查报告中的 8 项 Important 与 2 项 Minor 均已解决。本轮修复没有发现与这些问题直接相关的新回归。
- ⚠️ 真实 MySQL 仍未提供，因此凭据轮换失败回滚、并发任务复用、冻结迁移实跑及 MySQL 时间取回行为仍处于明确的未验收状态；实施报告继续如实保留这些限制。

### 逐项判定

| 原发现 | 判定 | 依据 |
| --- | --- | --- |
| Important 1：管理员会话隐式 JOIN 无法构造 | ✅ 已解决 | `backend/app/persistence/repositories.py:27-35` 抽出查询并显式使用 `AdminAllowlist.open_id == AdminSession.open_id`；新增 MySQL 方言编译测试覆盖原故障。 |
| Important 2：省略门店字段会清空历史资料 | ✅ 已解决 | `backend/app/admin/router.py:76-86` 用 `model_fields_set` 区分省略和显式 null；`backend/app/stores/domain.py:55-62` 合并现值，并在取消门店时保留编码和备注；preview/apply 均使用合并结果。 |
| Important 3：API 凭据轮换非原子 | ✅ 已解决 | `backend/app/persistence/repositories.py:88-98` 在单个 `sessions.begin()` 中锁旧记录、写新凭据、撤销旧凭据和写审计日志，任一步异常都会由事务整体回滚。真实 MySQL 失败注入仍按计划留待联调。 |
| Important 4：初始迁移依赖可变 `Base.metadata` | ✅ 已解决 | `backend/migrations/versions/0001_initial.py:1-47` 已改为冻结的显式建表、索引、种子和逆序删表，不再导入应用模型。 |
| Important 5：门店员工端点缺少世代/版本参数及管理别名 | ✅ 已解决 | `backend/app/main.py:135-137` 和 `backend/app/admin/router.py:65-68` 均接收并透传 `dataset_epoch`、`data_version`，管理端别名已注册。 |
| Important 6：白名单/API 凭据写入无审计 | ✅ 已解决 | `backend/app/persistence/repositories.py:80-126` 将创建、轮换、撤销、添加和删除操作与脱敏 `ChangeLog` 放在同一事务；日志数据不含 secret/hash。 |
| Important 7：MySQL naive UTC 时间直接序列化 | ✅ 已解决 | `backend/app/web.py:4-7` 提供统一 UTC 边界；状态、任务列表、变更日志、白名单和客户端响应均调用该转换。 |
| Important 8：初始化前任务复用没有稳定锁 | ✅ 已解决 | 初始迁移写入 `system_setting.task_queue_lock`；`backend/app/persistence/repositories.py:143-148` 锁定并强制检查该稳定行，避免依赖尚未初始化完成的数据版本行。 |
| Minor 1：来源 ID/客户端名称可在 trim 后为空 | ✅ 已解决 | `backend/app/admin/router.py:137-181` 对 `open_id` 和客户端名称增加长度限制、去空格及去空格后的非空校验；门店部门 ID 也增加长度限制。 |
| Minor 2：任务列表超过 limit 后不可访问 | ✅ 已解决 | `backend/app/main.py:155-176` 增加稳定的 `(created_at, id)` 边界游标、`limit + 1` 取数和 `next_cursor`。 |

### Direct Regression Check

- 未发现本轮修复引入的直接功能回归。门店 preview 返回合并后的具体值，没有把内部 `UNSET` 暴露到 HTTP；凭据审计仅记录名称、撤销状态和替代客户端 ID；任务锁缺失会明确返回 `DATABASE_SCHEMA_INCOMPLETE`，不会静默失去复用保证。
- 修复同时增加了针对会话 SQL、门店字段保留、UTC 转换、门店员工版本参数和任务游标契约的测试。实施报告记录针对性测试 `8 passed`、全量回归 `26 passed, 1 warning`；本次限定复审未重复执行测试。

### Assessment

**Spec verdict:** ✅ Compliant for the reviewed findings

**Task quality:** Approved

**Reasoning:** 修复与原问题一一对应，关键操作已收拢到明确的事务和序列化边界，迁移也已冻结。剩余事项都是报告中明确保留的真实 MySQL 验收工作，不属于本轮仍可从代码直接修复的开放发现。
