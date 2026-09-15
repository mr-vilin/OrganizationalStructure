# Task 2 修复轮 2：离职生命周期不依赖部门可读性

处理 task-2-rereview.md 未关闭 AC25 与对应新回归；其余通过项保持。

- 根代理已用 SQLite 行为夹具复现：本地 active 员工 u，有 LoginIdentity 和活动会话；Candidate 明确 status=inactive、department_ids 包含不可读新部门；_defer_unresolved 延后整个员工，最终仍 active 且会话未撤销。
- 将明确生命周期事实与关系完整性分开处理：确认 inactive 必须更新已有员工状态、结束其当前活动关系/门店归属并原子撤销管理员会话；未解析新部门继续隔离，不创建 active 假部门。最后已知名称/来源 ID 等资料保留；新增不完整关系可保持 pending。处理新/已有员工均须满足外键和审计原子性。
- 同时覆盖详情中的关系/父字段缺失而生命周期明确 inactive 的情形：不能因为 normalize_user 先抛 MEMBERSHIP_UNREADABLE 就丢掉可信离职证据；必须先确认请求来源 ID、显式布尔状态，禁止根据错误码或缺席猜离职。若生命周期本身不可读，仍只 pending 保留。
- 测试先 RED 后 GREEN：不可读部门的明确离职；关系字段缺失的明确离职；生命周期缺失不能撤权；关系/日志失败导致事实和撤权同事务回滚；新员工不完整关系不能生成假部门。复用现有SQL行为夹具，真实MySQL仍未验收。
- 完成后针对测试、后端全套、离线迁移验证，追加 task-2-report.md；不改前端，不派生代理。当前前端实现中，待root正式followup才开始修改。
