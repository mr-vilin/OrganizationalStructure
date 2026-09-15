### Finding Verdicts

- **R1 新破坏：409 后父列表刷新覆盖批量编辑草稿** — **ADDRESSED（行为已修复，要求的父页面集成测试仍缺失）**。`frontend/src/components/StoreEditor.tsx:16` 的初始化 effect 只依赖 `open`，同一打开会话中父列表返回新对象/新数组不再重置表单；`StoreEditor.tsx:18-20` 又把预览有效性绑定到最新 `dataVersion`，冲突后必须按新版本重新预览。`frontend/src/components/StoreEditor.test.tsx:13-15` 用新对象数组、两个 changes 和 version 43 验证了组件级流程；根代理的真实 Edge 复验进一步确认 OrganizationPage 中两部门 apply 409 后草稿完整保留，再次 preview/apply 使用 version 2 并提交完整两项。行为问题已关闭。不过修复简报明确要求“新增父页面集成测试”，现有 `OrganizationPage.test.tsx` 没有打开编辑器或提交批量 changes，因此这部分自动回归保护尚未满足。

- **原 Finding 3：子资源 409 后重读父子整组且不再发送无版本请求** — **NOT ADDRESSED**。`frontend/src/pages/OrganizationPage.tsx:20-23` 与 `frontend/src/pages/StoresPage.tsx:13-15` 已用父数据、epoch、version 作为原子门槛；父 reload 清空 meta 时子 path 会变为 null，代码层面关闭了无版本请求窗口。问题在于两页仍调用通用 `readAll`，而 `frontend/src/services/readAll.ts:5,32-34` 会在把 `DATASET_CHANGED` 暴露给页面前，用完全相同的旧父版本重试三轮。`OrganizationPage.test.tsx:10-17` 甚至以“前三个员工请求均返回 409”来驱动父列表第二次读取，证明实现仍在重复旧版本，而不是第一次 409 即协调重读父子整组。这直接违反修复简报第 2 项。并且三次上限只约束单次 `readAll`：错误暴露后页面 effect reload 父资源，子 path 暂停并清空 error；父资源返回后会创建新的 `readAll` 三次循环。若服务持续返回 409，这个“3 次子请求→父 reload→再 3 次”的整组循环没有总上限，同样不满足“有限重试避免循环”。门店页虽有相同页面逻辑，却没有 `StoresPage.test.tsx` 或等价组件测试覆盖其 409 协调路径。影响是持续版本冲突会造成无限请求循环、延迟恢复并放大后端负载。

- **R1 新破坏：父 meta 清空期间发无版本子请求** — **ADDRESSED（门店页缺自动化回归覆盖）**。`OrganizationPage.tsx:21-22` 和 `StoresPage.tsx:13-14` 只有在父数据、epoch、version 同时存在时才构造子 URL；否则传入 null，`useAllResource` 不会发请求。组织页测试 `OrganizationPage.test.tsx:10-17` 断言所有已发员工 URL 都带 epoch/version。门店页实现采用相同门槛，但本轮没有相应测试；根代理对子请求 409 的浏览器复验仍在进行。

- **R1 新破坏：无搜索时部门树不能手动展开** — **ADDRESSED（自动化测试仍不充分）**。`frontend/src/pages/OrganizationPage.tsx:28` 在无搜索时完全省略 `expandedKeys`，Tree 恢复非受控展开；搜索时才传入包含命中节点及祖先的受控 keys，清空后重新回到可操作状态。根代理已在真实 Edge 中验证手动三级折叠/展开、搜索保留祖先、清空后再次折叠/展开均通过。`OrganizationPage.test.tsx:19-22` 只验证深层搜索、祖先保留和清空后选择；由于初始 `defaultExpandAll` 已展开全部节点，测试仍没有真正覆盖简报要求的“不搜索时手动展开三级节点”。

- **原 Finding 5：日志使用真实来源枚举并覆盖操作、操作者、UTC 起止和重置** — **NOT ADDRESSED（实现与实浏览器行为已修正，测试少 UTC 起止）**。`frontend/src/pages/LogsPage.tsx:14,20` 现在发送后端真实枚举 `source=feishu`，时间也通过 `toISOString()` 转成 UTC；`LogsPage.test.tsx:8-16` 是实际组件测试，覆盖 source、action、actor 和重置。根代理也已在真实 Edge 中验证 action/source=feishu/actor 查询及重置通过。但测试没有操作日期范围，也没有断言 `committed_after` / `committed_before` 的 UTC ISO 参数，未达到修复简报明确列出的完整组件测试范围。

- **原 Finding 8：核心交互自动化与浏览器验证证据** — **NOT ADDRESSED**。报告记录 8 个测试文件、18 项测试、build 通过和 Ant Design lint 0 issues（`docs/superpowers/task-3-report.md:86-90`），本复审依要求未重复运行。根代理已补充真实 Edge 证据：批量冲突草稿、计划 03:00/Asia/Shanghai、真实员工 shape、手机搜索选择并关闭 Drawer、手动三级树与日志筛选均通过，且无 pageerror。仍缺父页面批量冲突集成测试、门店页父子版本测试、真正手动三级展开测试和日志 UTC 起止组件断言；子资源持续 409 的有限协调仍未通过实现审查。

- **现有通过项与 Settings useForm 警告** — **NOT ADDRESSED（Minor）**。根代理确认计划保存、员工 shape 和手机 Drawer 行为保持通过；但真实 Edge 仍出现 useForm 未连接警告。`frontend/src/pages/SettingsPage.tsx:15-16,21` 在 schedule 数据到达时 effect 调用 `setFieldsValue`，而表单只在对应 Tab 内容实际挂载后才连接，警告路径仍存在。它不阻断用户操作，但本轮没有消除简报点名的质量问题。

- **deploy/README 恢复流程回归** — **ADDRESSED**。`deploy/README.md:65-97` 的 Bash 块恢复了 `set -euo pipefail`，先停止应用并检查固定备份文件/目标 MySQL，随后在第 76-78 行成功备份明确的 `organization` 库；只有此前步骤成功才会在第 80-84 行删除、重建并导入同一目标库，之后依次迁移、重置世代和凭据、重启健康检查。硬编码且反复标明的目标库为 `organization`，覆盖步骤也有明确警示，解决了失败后继续执行和旧 schema 残留导致 Alembic CREATE 冲突的已指出回归。

### New Breakage in the Fix Diff

- **Important — 手机组织页发生整页横向溢出。** 根代理在 390px Edge 视口选择部门、关闭 Drawer 并额外等待 600ms 后确认 `document.documentElement.scrollWidth=788`，截图 `C:/Users/Vilin/AppData/Local/Temp/qa-fail-mobile-tree.png`。`frontend/src/styles.css:1` 的窄屏规则只把 `.org-grid` 改为单列；`frontend/src/pages/OrganizationPage.tsx:29` 的人员 Card 标题操作区和内部表格仍能撑宽页面，未把宽表限制在卡片内部滚动。触发为手机选择部门并显示人员卡片；影响是页面可横向滚动近两倍视口宽，操作与内容会落到屏外。这是本轮要求保持手机主流程时发现的直接响应式回归。

### Out-of-Scope Observations

- Task 2 后端实现仍由另一代理处理；本复审只按当前约定接口检查 Task 3 R2，未把跨任务尚未完成的后端验证计为本轮缺陷。
- 根代理尚在进行子资源 409 的真实浏览器复验；本报告只记录已收到的浏览器证据，不预判待完成结果。

### Verdict

**Fix round:** Findings remain open — 父子请求仍在第一次 409 后用旧父版本重复三轮，且跨父 reload 的整组循环没有总上限；指定的父页面批量冲突、门店页版本协调、手动三级展开、日志 UTC 起止自动化覆盖仍不完整；手机组织页出现确认的整页横向溢出；Settings 的 useForm 警告仍存在。批量冲突草稿的真实行为、无版本请求门槛、Tree 交互、`source=feishu` 和 Bash 恢复顺序本身已修正。

**Spec compliance:** ❌ Issues remain。

**Task quality:** Needs fixes。
