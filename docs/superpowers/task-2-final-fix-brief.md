# Task 2 整体审查修复：明确删除部门的独立生命周期

整体审查代理 final_review 确认 AC19 的 Important（同一问题的三个路径）。仅处理这些问题及直接回归。root 正式派发前不要修改；前端当前仍在实施。

## 已确认路径

- 门店 S → 部门 D → active 员工 U；只收到 D 已验证的 inactive 详情。Publisher 仅 upsert Department，没有结束 D 的 EmployeeDepartment.active；员工仍被查为 D 当前人员，_nearest_store 遇inactive节点继续沿旧parent向上，错误派生 S。
- normalize_department 先要求非空 parent，再读显式布尔 is_deleted。明确删除但parent字段缺失会仅pending；或者parent='missing'被_defer_unresolved整体移除，旧D保持active，关系没有结束。
- 尚active子部门位于明确deleted祖先下时，不能沿deleted节点的旧parent继续派生更上层门店；也不得据此级联猜测所有子部门都deleted。

## 修复要求

1. 来源ID核对、显式布尔生命周期校验后，明确删除部门可独立发布；新父引用不可读时保留已知旧资料/父引用，候选关系保持pending，不编造部门或根关系。
2. 部门明确inactive同事务结束其直接当前员工关系，保留历史，不影响员工其他有效兼职关系；不能将员工本人猜为离职或因此撤销其管理员会话。
3. 后续 active 员工详情仍包含已知inactive部门时不能重新激活该关系；来源明确恢复部门后按可信关系重新回查/发布才恢复。
4. 门店派生遇明确inactive部门/祖先停止沿旧父链，给出符合既有“未知/不可信”规则的状态，不能越过失效节点派生门店。不猜级联删除子部门。
5. 事实、关系、投影、审计、版本在同一事务；无变化重复事件不增加版本。

## 验证

按 TDD 先RED：部门删除、缺失/不可读父的明确删除、仅父或生命周期不可读不能误删、来源ID不符、其他兼职关系保留、员工/管理员仍active、后续回查不能复活inactive关系、deleted祖先阻断派生、发布/审计失败回滚、同事件无变化版本不增。复用SQL行为夹具；真实MySQL继续跳过。

完成 targeted/full backend tests 与离线迁移，追加 task-2-report.md 的整体修复段；不改前端、不要派代理。完成后停止，交 final_review 做限定复审。

## 同轮合并：日志分页游标类型

final_review 确认 /admin/api/change-logs 的 next_cursor 为数字 ChangeLog.id，而统一客户端只读取 string|null，导致日志超过100条时历史页面不可达。后端统一返回字符串游标，null规则保持，查询参数可继续安全解析整数。补 HTTP envelope 与多页读取测试，验证无跳漏；不改前端。
