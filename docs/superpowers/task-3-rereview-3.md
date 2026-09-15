### Finding Verdicts

- **父子固定版本首次 409 立即整组重读** — **ADDRESSED**。`frontend/src/services/readAll.ts:5-7,34-36` 识别 URL 中外部绑定的 `dataset_epoch/data_version`；这类请求第一次收到 `DATASET_CHANGED` 就直接上抛，不再在 `readAll` 内重复旧基准。`frontend/src/pages/OrganizationPage.tsx:20-24` 与 `StoresPage.tsx:13-16` 仅在父数据、epoch、version 同时就绪时发送子请求，并在冲突后 reload 父资源。`readAll.test.ts`、`OrganizationPage.test.tsx:10-18` 和 `StoresPage.test.tsx:8` 分别覆盖单次上抛、组织整组恢复和门店整组恢复；两页测试均断言没有无版本子请求。

- **持续 409 的整组总上限与手动重试** — **ADDRESSED**。组织页 `OrganizationPage.tsx:23-27`、门店页 `StoresPage.tsx:15-19` 分别以页面级 ref 限制自动父级 reload；成功取得子数据后才重置预算。预算耗尽时保留 `DATASET_CHANGED` 给 `ResourceState` 显示错误，不再自动循环；其重试按钮调用包装后的 `retryGroup`，明确重置预算并重读父资源。`OrganizationPage.test.tsx:32-35` 覆盖持续冲突后显示错误和手动重试。自动恢复期间父 meta 会清空，版本门槛使子 path 为 null，因此手动与自动流程都不会产生无版本请求。

- **OrganizationPage 两 changes 的真实父页面 409 集成回归** — **ADDRESSED**。`OrganizationPage.test.tsx:37-62` 从页面勾选两个部门、修改备注、preview、首次 apply 409，模拟父列表以新对象和新 version 返回；随后断言草稿仍在、第二次 preview 使用 version 2 且包含两个 changes，并完成第二次 apply。它补齐了 R2 仅 rerender StoreEditor 的覆盖缺口。`StoreEditor.tsx:19-20` 同时对 preview 和 apply 两个 409 分支清除旧预览、保留表单并触发父刷新；`StoreEditor.test.tsx:17` 另覆盖首次 preview 即 409 的 F2 路径。

- **StoresPage 父子版本协调覆盖** — **ADDRESSED**。`StoresPage.tsx:13-19` 与组织页采用同样的版本门槛、有限预算和父级手动重试；`StoresPage.test.tsx:8` 验证首个门店员工请求 409 后立即读取父 version 2、第二个子请求成功，且所有子 URL 都包含 epoch/version。

- **部门树三级手动展开、搜索祖先与清除后继续操作** — **ADDRESSED**。`OrganizationPage.tsx:28,32` 只在搜索时传受控 `expandedKeys`，无搜索时交给 Tree 自身维护展开状态。`OrganizationPage.test.tsx:20-30` 实际点击 Tree switcher 折叠并再次展开，在深层搜索中确认祖先和命中节点存在，清空后继续操作。根代理在 R2 的真实 Edge 中也已验证三级折叠/展开、搜索和清除后的再次展开。

- **日志 UTC 起止参数及真实对象类型** — **ADDRESSED**。`LogsPage.tsx:14` 使用 `toISOString()` 发送 `committed_after/committed_before`；`LogsPage.test.tsx:18-20` 操作实际 RangePicker 并断言两个查询值均为 UTC `Z` 结尾。既有 source=feishu/action/actor/reset 测试保持。M1 也已在 `LogsPage.tsx:18` 把对象类型对齐为 `admin_allowlist`、`event`、`security`、`settings`、`dataset` 等实际审计值，避免旧 `admin` 筛选空结果。

- **390px 页面横向溢出** — **ADDRESSED**。`frontend/src/responsive.css:4-12` 限制应用壳、Layout、组织网格、Card 与 Table wrapper 的最大宽度和最小内容宽度，并在窄屏允许 Card 标题/操作区换行，表格仍由自己的 scroll 容器承载宽内容。实施报告记录 390×844 Edge 下组织、门店、同步、日志四页均为 `scrollWidth=390`，组织页实际选择部门后仍为 390 且无 pageerror。根代理正在独立复验；本报告不把尚未返回的独立结果冒充已完成证据。

- **Settings / StoreEditor 的 Form 未连接警告** — **ADDRESSED**。`SettingsPage.tsx:22` 给计划 Tab 配置 `forceRender`，异步 `setFieldsValue` 前表单已经挂载；StoreEditor 的 Form 始终位于其受控 Drawer 内并只在打开会话初始化（`StoreEditor.tsx:16,21-24`）。实施报告记录 R3 Edge 四项流程无 console warning；未通过过滤 console 隐藏问题。

- **F3：同步状态、摘要及终态刷新** — **NOT ADDRESSED**。`SyncPage.tsx:13,25` 已把待处理事件改为真实 queued，并把 incomplete 显示为“覆盖不完整”；但另外两项仍失效。第一，真实 `/admin/api/status` 由 `backend/app/persistence/read_service.py:32-35` 把 `last_full_sync_at` 放在 response `meta`（由 `_meta` 第 28 行生成），而 `SyncPage.tsx:11,25` 把它声明并读取为 `current.last_full_sync_at`，真实响应会一直显示“—”。第二，`useResource.ts:12-21` 每次轮询 reload 都先执行 `setData(null)`；`SyncPage.tsx:20` 随后无条件把 `previousDetailStatus.current` 写成 undefined。终态响应到达时 previous 已不是 queued/running，因而 jobs/status/events 的刷新分支不会执行。触发为 running 详情的一次正常轮询；影响是详情已 succeeded/failed，任务列表、初始化/覆盖摘要和事件仍可长期显示旧状态。当前也没有 `SyncPage.test.tsx` 用真实 loading 空档覆盖该转换。

- **F4：人员同步质量与可解释路径** — **ADDRESSED**。`EmployeePage.tsx:9` 展示员工 `sync_quality`，对 `pending_verification` 明确显示“保留旧资料，待核实”；部门表展示完整 `path` 与部门 `sync_quality`，门店表展示派生 `path_names`。Result 只有员工质量 complete 且主门店 resolved 时才使用成功状态，不再用绿色结果掩盖 pending 数据。

### New Breakage in the Fix Diff

- 除上述 F3 未关闭问题外，本轮限定的 R2 未关闭项及 F2/F4/M1 路径中未发现直接新破坏。

### Verification Evidence

- `docs/superpowers/task-3-report.md` 的修复轮 3 记录前端 9 个测试文件、24 项测试全部通过，生产 build 通过，Ant Design lint 0 issues；本复审按要求未重复运行。
- 同一报告记录 Edge 390×844 的组织批量冲突、计划、人员契约及组织/门店/同步/日志宽度检查通过。根代理的独立 R3 浏览器复验仍在进行，因此最终整体验收可继续等待该独立证据，但当前源码与既有报告之间没有发现矛盾。
- 后端 F1 正在独立修复，本轮未读取或裁决其在途修改。

### Verdict

**Fix round:** Findings remain open — F3 的最后全量同步时间读取了错误的 envelope 层级，详情轮询又会在 loading 空档丢失前一活动状态，导致终态后外围资源不刷新。其余首次固定版本 409、有限恢复、批量草稿、Stores、三级树、UTC、390px、Form warning 及 F2/F4/M1 均已闭合。

**Spec compliance:** ❌ Issues remain。

**Task quality:** Needs fixes。
