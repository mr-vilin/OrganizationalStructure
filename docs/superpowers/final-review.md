# 整体最终代码审查

日期：2026-09-15。方式：独立只读代码审查，采用 `superpowers:requesting-code-review` 工作流；本审查不运行测试、不修改实现。

**最终裁决：Approved（代码审查）。F1～F5 和 M1 均已关闭，没有开放的 Critical/Important。真实 MySQL、飞书企业联调及部署/恢复演练仍未验收。** 下文保留原发现与各轮复审历史，最终状态以本段和末尾裁决为准。

## 审查范围与依据

- 已审查后端 HTTP/鉴权、OAuth 身份绑定、门店规则与投影、SQL 持久化与迁移、采集/发布/事件/租约、覆盖重新验收，以及 `deploy/`、`Dockerfile`、`compose.yaml`。
- 依据 `方案.md`、`同步与接口设计.md`、`决策与验收.md`、`docs/superpowers/plans/2026-09-15-system-build.md`。
- 已审查全部业务页面、鉴权请求层、Organization/Stores/StoreEditor、版本协调与响应式 CSS，并完成后端 F1/F5、前端 F3/M1 最终限定修复复审。
- 用户要求先完成代码，稍后提供数据库。真实 MySQL、真实飞书、Docker 上线与恢复演练未执行，不作为代码缺陷，也不标记验收通过。

## Critical

当前已审范围未发现可复现 Critical。

## Important

### F1：已验证的部门删除没有完整结束当前关系，且仍依赖父引用可读

**状态：后端最终修复限定复审已解决。** 详见下方“后端 F1/F5 最终限定复审”；以下保留原复现作为审查历史。

**位置：** `backend/app/sync/publisher.py:39`、`backend/app/sync/publisher.py:108`、`backend/app/sync/collector.py:34`、`backend/app/directory/domain.py:49`。

**复现 A：** 已有有效门店 S，其子部门 D 与员工 U 的主部门关系有效；只收到 D 的详情，来源明确 `status.is_deleted=True`。Publisher 仅更新 Department.status，没有将 D 的 EmployeeDepartment.active 结束；员工查询仍把 U 列为 D 当前员工。领域派生跳过 inactive D 后沿旧 parent 继续向上，因此仍把 S 判为 U 的主门店。

**复现 B：** 相同状态下，可信删除详情同时缺少 `parent_department_id`，规范化在解析生命周期前抛出 `FEISHU_PARENT_UNREADABLE`，D 整体只进入 pending；或返回未知父 ID，被 `_defer_unresolved` 整体移出待发布集合。两种情况均保留 D 为 active 和其全部当前关系，虽已有可靠删除证据。

**协调代理复现证据：** 使用现有 SQLite 事务夹具实际发布单个 D 的 inactive 候选后，得到 `department_status=inactive`、`membership_active=True`、`old_store_still_present=True`。该结果验证复现 A；不代表真实 MySQL 已执行。

**影响与依据：** AC19 要求已验证部门删除或员工离职结束相关当前关系；AC13 要求派生结果与事实同一版本。当前行为会保留已经失效的当前归属，部门删除语义也与已修复的员工离职语义不一致。

**修复要求：** 可信部门删除独立于不可读的新父引用生效，保留最后已知资料与历史；同事务结束直接人员关系、写审计、重建投影并更新版本。不能经已删除祖先继续向上产生可信归属，也不能级联把尚未确认的子部门/员工标为失效。后续 active 员工详情包含已删除部门时不得恢复该当前关系。补充删除、缺失/未知父引用、其他兼职关系保留、后续回查及事务失败回滚的行为验证。

### F2：首次预览遇版本冲突后不能刷新基准版本

**状态：R3 代码复审已解决。** `StoreEditor.tsx:19` 的 preview 409 已设置冲突、清空预览并调用父页面 onConflict；组织/门店父页重新读取版本，表单 effect 不依赖刷新后的 departments，因此保留草稿。动态验证由协调代理执行，本审查不运行测试。

**位置：** `frontend/src/components/StoreEditor.tsx:19`；后端版本拒绝位置 `backend/app/stores/service.py:82`。

**复现：** 页面加载版本 N；后台同步提交 N+1；管理员填写门店变更后第一次点击预览。后端返回 409；`buildPreview` catch 仅提示错误，没有调用 `onConflict` 更新父页面基准。继续点击预览仍传 N，持续 409。已有 apply 的冲突处理不能覆盖此分支。

**影响与依据：** 正常后台更新会阻断门店编辑工作流；任务计划明确要求 409 后保留表单并重新预览。

**修复要求：** preview 的 409 同样清除旧预览、保留表单、触发父页面整组刷新；增加父页面级测试，证明下一次预览使用新版本且保留输入。

## Minor

### M1：管理员日志筛选值与实际对象类型不一致

**状态：已解决。** R3 已使用 `admin_allowlist`，最终限定修复补充 `membership`，并有组件测试验证两者可选；其他新增对象类型保持可选。原有全部日志读取入口不变。

**位置：** `frontend/src/pages/LogsPage.tsx:18`。

对象类型下拉使用 `admin`，但后端白名单变更写入 `admin_allowlist`（`backend/app/persistence/repositories.py` 的 add_admin/remove_admin）。选择该项将得到空列表，无法按界面提供的类别查到管理员增删记录。改为真实后端枚举并提供中文标签；`membership/security/settings/event/dataset` 等已产生的对象类型也应能选择。当前全部日志仍可读取，因此列为 Minor。

## 稳定前端补审发现（Important）

### F3：同步中心状态筛选和健康信息不符合后端契约

**状态：最终限定复审已解决。** queued 筛选、incomplete 文案、meta 时间与真实 loading 空档下终态刷新均已关闭；以下保留原问题和 R3 中间复审历史。

**位置：** `frontend/src/pages/SyncPage.tsx:13`、`:18`、`:23`。

- “待处理事件”传 `status=pending`，而后端收件箱使用 `queued`（`backend/app/feishu/events.py:23`），列表端点按值直接筛选（`backend/app/admin/router.py:198`）。只要数据库存在 queued 事件，用户点击“待处理事件”就得到空列表，真实积压不可见。
- `coverage_status=incomplete` 被公共 labels 映射为“未初始化”。已完成初始化但覆盖不完整时，页面会混淆两个独立状态，应分别显示“初始化已完成”和“覆盖不完整”。
- 状态接口通过 `meta.last_full_sync_at` 返回最近全量成功时间（`backend/app/persistence/read_service.py:28`），页面未读取或显示；发生持续故障时用户不能得知最后成功版本时间，违背 AC30 和 Task 3 同步页要求。
- 仅任务详情轮询，任务由 running 变为 succeeded/failed 后没有刷新 jobs/status/events；这些资源只在路径或 revision 变化时重读。创建任务后可以出现“详情成功、列表仍排队、初始化仍 pending”的长期矛盾，且页面没有统一刷新入口。应在任务终态刷新相关摘要/列表，并提供明确的刷新能力。

**修复验证：** 使用后端实际 queued/failed/succeeded 响应证明筛选有效；覆盖 complete/incomplete/unknown 与初始化分开；展示北京时间最近全量成功时间；推进任务终态后摘要和列表跟随更新。

**R3 剩余问题：** `SyncPage.tsx:25` 显示 `current.last_full_sync_at`，但后端值仍只在 `status.meta.last_full_sync_at`，所以真实响应显示“—”。`SyncPage.tsx:20` 无条件把 `previousDetailStatus.current` 赋为 `next`；每次轮询调用 useResource.reload 都先清空 data（`useResource.ts:15`），于是 previous 被改成 undefined，随后 succeeded 到达时不满足“前值是 running”的条件，刷新分支不会执行。应读取真实 meta 字段，保留最后一个非空状态并按任务 ID 隔离；用真实请求钩子的 loading 空档验证终态转换。当前源码中未发现 SyncPage.test.tsx，不能从其他页面测试推出该路径通过。

### F4：员工详情隐藏待核实质量与归属依据

**状态：R3 代码复审已解决。** `EmployeePage.tsx:9` 已展示员工及部门 sync_quality、部门完整路径和门店 path_names；pending + resolved 不再显示绿色成功，保留已知结果与待核实提示同时呈现。

**位置：** `frontend/src/pages/EmployeePage.tsx:9`。

后端合法响应可以同时包含 `status=active`、`sync_quality=pending_verification`、`primary_store_status=resolved`：不可读时保留最后已知事实，而不是宣称最新。当前详情忽略 `sync_quality`，仅显示有效和绿色“已解析”，完全隐藏待核实状态。此外后端已返回 `departments[].sync_quality` 与 `stores[].path/path_names`（`backend/app/persistence/read_service.py:185`），页面没有展示异常或任何归属路径，嵌套门店只有结果而没有依据。

**依据：** 方案第 3/4 节要求异常可见和归属路径解释；AC06、AC30 要求解释最近门店路径并展示质量。应显示员工/相关部门质量及路径，并让 pending 质量提示与保留的已知结果同时呈现；不能仅以 resolved 渲染无异常成功。

**修复验证：** 覆盖 pending_verification + resolved、异常部门、嵌套门店路径、正常 resolved，以及 unknown/inconsistent/inactive。

### F5：数字日志游标被丢弃，日志最多只能读取首 100 条

**状态：后端最终修复限定复审已解决。** 后端现统一返回字符串游标，见下方复审证据；以下保留原复现作为审查历史。

**位置：** `frontend/src/services/readAll.ts:29`、`backend/app/admin/router.py:190`。

后端 change-logs 的 next_cursor 是整数 ChangeLog.id，前端 readAll 仅接受字符串，其余直接改为 null。存在超过 100 条审计记录时，LogsPage 的默认 limit=100 响应携带数字 next_cursor，读取立即结束，分页器只能浏览首 100 条，旧记录无法继续获取。违反 Task 3 全部分页与 AC32 历史查询要求。应统一为字符串协议或兼容数字后转换为字符串；增加真实数字 next_cursor 的多页日志用例，不能只用字符串模拟日志响应。

## 前端 R3 整体补审

- 组织和门店子资源只在父集合与世代/版本就绪时发请求；固定版本 409 立即交回父页重新读取，父页设重试计数上限，未发现旧版本单独无限重试路径。
- 批量树使用 checkStrictly，预览发送明确勾选的全部变更；preview/apply 都经过版本拒绝，保存按钮还受草稿指纹约束。
- 表格横滚、网格 min-width 与窄屏卡片头换行已补，静态代码未发现原卡片头撑宽的直接回归；实际 Edge 尺寸和溢出由协调代理验证，本审查不把 CSS 阅读作为浏览器验证。
- F2/F4 通过本轮代码复审；M1 的管理员筛选值已修正；F3 尚未完整解决，新增 F5。**前端结论：Changes requested。**

## 后端 F1/F5 最终限定复审

审查范围仅 `task-2-final-fix-brief.md` 对应变更及直接回归；未运行测试、未重新全面探索，也未读取在途前端修复作为结论依据。

| 原发现 | 判定 | 代码与行为依据 |
| --- | --- | --- |
| F1：可信删除被不可读父引用阻断 | 已解决 | `collector.py:33` 先校验严格布尔生命周期，`:55` 核对请求来源 ID；已有 inactive 部门的缺失或未知新父引用经 `publisher.py:117`～`:126` 变成 lifecycle_only，保留旧资料/父引用，独立发布 inactive。未知新部门仍隔离 PendingFact，不编造根事实。 |
| F1：删除部门仍保留当前关系 | 已解决 | `publisher.py:48`、`:149` 在发布事务内结束该部门直接 active 关系并写 membership 日志；不改变员工本身状态、不撤销其会话、不结束其他兼职关系。`:67` 要求员工和目标部门都 active 才激活后续关系。 |
| F1：穿过失效祖先派生门店 | 已解决 | `directory/domain.py:45` 遇 inactive 节点停止，`:79` 处理已删除主部门为 unknown；`stores/service.py:114` 路径计算也同步停止，合法其他关系不再借用跨失效祖先的路径。子部门不会被级联标失效。 |
| F1：事务与无变更版本 | 已解决 | 上述事实、关系、日志仍位于 Publisher 同一事务，之后统一重建投影并更新版本；只结束当前 active 关系，重复未变化生命周期不制造额外变更。新增用例覆盖审计失败整体回滚与重复删除版本不增。 |
| F5：数字日志游标 | 已解决 | `admin/router.py:190` 使用 `str(page[-1].id)`，终页为 null；查询参数仍将数字文本解析为整数。与前端 string|null 消费契约一致。`test_log_pagination_http.py` 经真实 HTTP 路由连续读取 205 条、三页 100/100/5，断言类型、顺序和无跳漏。 |

未发现该修复范围内新的直接回归。协调代理独立报告后端 **95 passed / 6 MySQL skipped / 1 已有第三方 warning**；实施代理针对性 **12 passed**，离线迁移至 0003 成功。以上为已提供验证证据，本复审没有重复运行。真实 MySQL 和飞书生命周期仍未验收。

**后端限定结论：Approved。F1、F5 均关闭。**

## 前端 F3/M1 最终限定复审

仅复审既有问题与直接回归，不重新扩大全面探索；未运行测试或浏览器脚本。

- **F3 时间字段：已解决。** `frontend/src/pages/SyncPage.tsx:25` 改为 `formatTime(status.meta.last_full_sync_at)`，与后端真实 envelope 一致，Status.data 类型也删除错误字段。
- **F3 loading 空档与终态刷新：已解决。** `SyncPage.tsx:17`、`:20` 保存最后非空的任务 ID/状态；data 清空期间提前返回，不抹掉 running/queued。后续同任务进入 succeeded/failed 时调用 jobs/status/events 三组 reload，关闭详情时清空跟踪。既有定时器在终态停止，未发现此次变更造成的重复终态刷新回路。
- **M1：已解决。** `frontend/src/pages/LogsPage.tsx:18` 同时提供 membership 和 admin_allowlist；新增组件用例检查两项可选。后端 F5 的字符串游标契约保持不变。
- **验证证据：** 协调代理独立 Edge 脚本 `org-ui-sync-check.cjs` 通过，detailReads=2，第二次详情响应延迟 150ms 经过真实 useResource 加载空档，最后成功时间显示、终态后三组摘要请求、失败事件重试进入 queued 均通过，errors=[]。实施报告前端 25 passed，协调代理已确认 build 通过、AntD lint 0 issues。SyncPage 的实际 loading 回归由该浏览器检查覆盖；没有把不存在的 SyncPage.test.tsx 记为证据。

**前端限定结论：Approved。F3、M1 均关闭。**

## 已核查的关键边界

- 管理会话与只读凭据分离；管理写入校验 CSRF，白名单与撤销每次读数据库；可信离职独立撤销已有会话。
- OAuth 校验一次性 state、应用/租户绑定、登录用户映射和管理员白名单；错误与日志不回显秘密。
- 同步发布锁定租约和内容版本行，事实、投影、日志、任务状态同事务；本地门店属性按发布时数据库现值重算。
- 缺页失败不发布半轮；未知事实隔离于 PendingFact，缺席不直接视为离职；scope 变更使覆盖验收失效。
- worker 的心跳、代际隔离和过期任务恢复有清晰边界；事件持久化后再回查来源。
- 恢复工具更换世代、撤销会话与只读凭据、隔离旧任务/事件并要求重新初始化；部署保留迁移先于应用、必要进程退出整体重启、未知 API 不回退 HTML。
- 稳定前端补审：业务 401/403 通知门禁重新校验，会话资源重读时清除旧业务状态；CSRF 由会话响应设置且写请求携带。客户端凭据只从创建/轮换响应进入本地弹窗状态，关闭时清空，已有凭据列表不含秘密。日志时间按 ISO UTC 提交。上述路径未发现新的阻断问题。

## 已有验证证据与限制

协调代理最终验证报告：后端 `95 passed / 6 MySQL skipped`；前端 `25 passed`、生产 build 通过、AntD lint `0 issues`；部署 `5 passed`；依赖 `pip check` 无冲突；离线迁移和入口导入通过。本审查只读取代码与报告，没有亲自重新执行测试、构建或浏览器检查，也不将上述结果扩大为真实环境验收。

## 当前结论

**Approved（代码审查）。** F1～F5 和 M1 均已解决，限定复审没有发现新的直接阻断回归。当前没有开放的 Critical/Important；先前 Changes requested 段落是审查历史，已由最终复审替代。

代码审查与模拟/本地验证不等于真实环境验收。真实 MySQL 的并发锁、事务与恢复，目标企业飞书权限、OAuth、生命周期及事件，Docker 部署与生产运行均按用户既定顺序，在提供环境后执行；本报告不宣称这些项目已通过。
