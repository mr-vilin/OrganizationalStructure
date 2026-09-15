### Finding Verdicts

- **1. 多选批量入口只处理 `checked[0]`** — ADDRESSED。`frontend/src/pages/OrganizationPage.tsx:23,27` 将全部勾选部门传入编辑器；`frontend/src/components/StoreEditor.tsx:16,19-20` 用完整 changes 预览并提交。`frontend/src/components/StoreEditor.test.tsx:9-14` 验证两项均进入请求。
- **2. 预览 Modal 遮挡确认且关闭后清空 preview，apply 不可达** — ADDRESSED。`frontend/src/components/StoreEditor.tsx:24` 把“确认提交”放入 Modal 的 `onOk`，取消只关闭 Modal并保留 preview；交互测试实际点击该按钮并观察第二次请求（`StoreEditor.test.tsx:9-14`）。
- **3. 跨端点没有锁定父资源世代/版本，409 不会重读整组资源** — NOT ADDRESSED。`frontend/src/pages/OrganizationPage.tsx:20-21` 和 `frontend/src/pages/StoresPage.tsx:12-13` 已把父 meta 加到子请求；但子请求 409 后仍只由 `readAll` 用同一旧版本重试三次，页面没有收到冲突后 reload 父资源的路径。`onConflict` 仅用于 StoreEditor apply，并不处理员工读取冲突。根代理浏览器请求记录还确认：父资源 reload 将 meta 清空期间，选中部门仍存在，于是先发出一次完全不带 epoch/version 的子员工请求，父资源返回后才再发 v2 请求。触发为父列表刷新或数据发布；结果既可能停在 409 错误态，也存在无版本子请求短暂成功并渲染混代数据的窗口。应在父 meta 不完整时令子 path 为 null，并由页面级协调器在冲突时重读父与子整组。
- **4. 业务请求 401/403 后门禁不接管** — ADDRESSED。`frontend/src/services/http.ts:39-45` 清空内存 CSRF 并发出鉴权失败事件；`frontend/src/components/AuthGate.tsx:17-24` 收到事件后重验 session 并卸载业务页面。`frontend/src/services/http.test.ts:35-40` 覆盖事件发送。
- **5. 日志缺少操作/结束时间且字段与时间格式不符合接口** — NOT ADDRESSED。`frontend/src/pages/LogsPage.tsx:10-16` 已补 action、actor、起止时间、UTC ISO 和重置；但“操作来源”的飞书同步仍提交 `source=sync`（第 16 行），后端实际日志写 `source=feishu`，因此该筛选仍会返回空结果。应使用契约的真实枚举并增加 URL 行为测试。
- **6. 树搜索没有保留祖先与原层级** — ADDRESSED。`frontend/src/pages/OrganizationPage.tsx:22,26` 从命中节点沿 parent 链收集祖先、保留层级、展开并高亮命中。
- **7. 窄屏部门树未进入 Drawer** — ADDRESSED。`frontend/src/pages/OrganizationPage.tsx:24,26-27` 提供窄屏入口、受控 Drawer 并在选择后关闭；`frontend/src/responsive.css:1-7` 隐藏窄屏常驻树。根代理浏览器已验证手机视口搜索、选择后关闭 Drawer 可用。
- **8. 缺少核心交互测试与浏览器验证证据** — NOT ADDRESSED。`frontend/src/components/StoreEditor.test.tsx:9-19` 新增了批量和 409 两项交互，`frontend/src/services/http.test.ts:35-40` 覆盖鉴权通知；但修复 brief 明确要求的后端真实 shape、日志过滤和树搜索交互测试均不存在。报告 `docs/superpowers/task-3-report.md:73-75` 记录 15 项测试/build/AntD 0 issues。根代理已补浏览器验证：schedule 保存 03:00/Asia/Shanghai、员工真实 shape、手机搜索选择关闭 Drawer 均通过；同时复现了 409 覆盖输入和树无法展开，故浏览器证据现已具备，但暴露的问题仍需修复。
- **9. `status=inactive` 被默认显示有效** — ADDRESSED。`frontend/src/domain.ts:2-5,17-18` 改为真实 status 枚举且未知不再默认有效；组织和门店页面直接按 status 渲染（`OrganizationPage.tsx:27`、`StoresPage.tsx:15`）。
- **10. 员工详情字段与后端数组结构不兼容** — ADDRESSED。`frontend/src/domain.ts:4` 与 `frontend/src/pages/EmployeePage.tsx:9` 使用明确的 departments/stores 结构；后端 `backend/app/persistence/read_service.py:177-186` 已输出对应详情、路径和主归属字段。
- **11. 部门缺 notes 导致编辑时可能清空既有备注** — ADDRESSED。后端 `backend/app/persistence/read_service.py:155-174` 在部门和门店读取中返回 notes，前端 `frontend/src/domain.ts:3` 将其列为必备字段，编辑器 `StoreEditor.tsx:16` 按每个部门原值初始化。
- **12. 同步状态、阶段、尝试数字段错配** — ADDRESSED。`frontend/src/pages/SyncPage.tsx:12-23` 读取 `initialization_status`、connection、事件时间，并用后端实际 `phase`、`attempt`、`progress` 展示任务；失败事件也按接口支持安全重试。
- **Minor 1. Vite 缺少 `/auth` 代理** — ADDRESSED。`frontend/vite.config.ts:8-12` 已补代理。
- **Minor 2. 设置页使用静态 message** — ADDRESSED。`frontend/src/pages/SettingsPage.tsx:1-17` 改用 `App.useApp()`；报告 `docs/superpowers/task-3-report.md:75` 记录 Ant Design 检查为 0 issues。

### New Breakage in the Fix Diff

- **Important — 409 后声称保留输入，实际父资源刷新会重置表单。** `frontend/src/components/StoreEditor.tsx:16` 的初始化 effect 依赖 `departments`；apply 409 时第 20 行先保留表单再调用 `onConflict()`，父页面 reload 后会传入新数组并触发第 16 行用服务器值覆盖用户修改。现有测试 `StoreEditor.test.tsx:15-19` rerender 时复用了同一个 `oneDepartment` 数组，因此没有模拟真实 reload，也无法发现覆盖。根代理浏览器已实际复现：用户备注在 409 后从“用户修改必须保留”恢复成“门店原备注”。应在同一编辑会话中把初始表单与父资源刷新解耦，或显式保存用户 draft 后以新版本重建 preview；测试需用新对象/新数组模拟 reload 并断言修改值仍在。
- **Important — 非搜索状态下部门树无法手动展开。** `frontend/src/pages/OrganizationPage.tsx:22,26` 在无搜索时仍显式传入 `expandedKeys={undefined}`，修复把 Tree 带入错误的受控展开状态；根代理在桌面和窄屏均复现点击展开后不显示子节点，只有输入搜索、代码提供 expanded 数组后才能展开。影响是正常浏览组织树的主路径不可用。应在无搜索时完全省略 `expandedKeys` 属性或维护受控 expanded state，并补点击父节点展开子节点的交互测试。
- **Important — 父资源 reload 的 meta 清空阶段会发无版本子请求。** `frontend/src/pages/OrganizationPage.tsx:20-21` 和 `frontend/src/pages/StoresPage.tsx:12-13` 在父数据仍保留选择、但 hook 已把 meta 重置为空时继续构造子 URL；`query` 会省略 undefined 版本字段。根代理浏览器请求记录确认先出现无 epoch/version 的员工请求，随后才出现 v2 请求。该窗口破坏修复本来要建立的跨端点一致性，且无版本响应可能短暂覆盖界面。应将“父数据、epoch、version 均就绪”作为发起子请求的原子前置条件。

### Out-of-Scope Observations

- Task 2 的安全修复仍在进行，但本轮前端使用的会话、CSRF、状态和设置接口契约未因此改变。

### Verdict

**Fix round:** Findings remain open — 原 Finding 3（409 时未重读父子整组资源且 reload 窗口发送无版本子请求）、Finding 5（日志飞书来源值仍错误）、Finding 8（缺少指定交互测试），以及修复差异新增的 Important：StoreEditor 在真实冲突刷新后覆盖用户输入、部门树在非搜索状态无法手动展开、父 meta 清空阶段发起无版本子请求。

**Spec compliance:** ❌ Issues remain。

**Task quality:** Needs fixes。
