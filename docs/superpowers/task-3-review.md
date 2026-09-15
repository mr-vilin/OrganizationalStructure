### Spec Compliance

- ❌ Issues found：核心页面和真实接口请求层已交付，但“批量预览与提交”“跨端点同一世代/版本”“全局处理 401/403”“日志按操作、操作者和时间过滤”“窄屏树进入抽屉”“浏览器验证证据”等要求尚未完整实现。具体证据见下列 Important / Minor 问题。
- ⚠️ Cannot verify from diff：`frontend/src/pages/SyncPage.tsx:6` 与 `frontend/src/pages/SettingsPage.tsx:6` 依赖 Task 2 正在实现的 `/admin/api/status` 扩展、`/admin/api/settings/reconcile-schedule` 和 `/admin/auth/session` 等接口；当前只能核对前端预期，无法完成跨任务联调验收。真实 MySQL、飞书 OAuth、通讯录权限和远程同步也按实施报告保留为未验收。

### Strengths

- `frontend/src/services/http.ts:18-45` 集中处理 cookie、JSON envelope、CSRF、网络失败和非 JSON 响应；`frontend/src/services/http.test.ts:5-35` 对这些关键边界给出了有意义的行为断言。
- `frontend/src/services/readAll.ts:4-36` 会在分页时携带首页世代/版本，检测响应漂移、重复游标，并对 409 做有限次数整轮重读，避免把两代数据拼在一起。
- `frontend/src/components/StoreEditor.tsx:13-18` 会使用后端规范化后的 change 建立预览指纹；表单变化或 apply 409 后会阻止旧预览提交并保留表单，符合单项编辑的冲突保护目标。
- `frontend/src/components/AuthGate.tsx:11-32` 不绕过后端会话，能够区分首次登录、无权限和后端不可用；`frontend/src/pages/SettingsPage.tsx:6` 只在创建/轮换响应中展示一次性 secret，列表路径没有渲染 secret 或哈希。
- `frontend/src/pages/OrganizationPage.tsx:22` 使用 `Tree.checkStrictly` 实现独立勾选；各业务列表通过 `useAllResource` 拉取完整分页，表格也提供客户端分页和横向滚动。

### Issues

#### Critical (Must Fix)

- 无。

#### Important (Should Fix)

1. `frontend/src/pages/OrganizationPage.tsx:21-25`：界面允许勾选多个部门并显示“批量设置（N）”，但点击后只取 `checked[0]` 打开单部门编辑器，`StoreEditor` 也始终只提交一个 change。触发方式是勾选两个或更多部门后执行批量设置；用户会以为全部勾选项已经预览和保存，实际只有第一项被修改，属于核心规格“批量预览与提交”缺失。应让编辑器接收全部勾选部门，构造完整 changes，一次预览全部规范化结果与影响，再用同一数组提交；或在实现前移除具有误导性的批量入口。

2. `frontend/src/components/StoreEditor.tsx:15-18`：预览成功后立即渲染一个 `footer={null}` 的 Modal；可执行 apply 的“确认保存”按钮仍位于被 Modal 遮挡的 Drawer footer。用户关闭 Modal 时，`onCancel` 又执行 `setPreview(null)`，随即禁用“确认保存”。触发方式是任何单项或所谓批量门店编辑先点“预览影响”；结果是没有可达路径调用 `apply()`，所有门店修改都无法提交。应把最终确认按钮放进预览 Modal 并从那里调用 apply，或关闭 Modal 时保留有效 preview、明确提供返回编辑/确认提交两个动作。

3. `frontend/src/pages/OrganizationPage.tsx:16-18`、`frontend/src/pages/StoresPage.tsx:8`、`frontend/src/services/readAll.ts:12-20`：`readAll` 只锁定单个端点自己的后续分页，页面随后读取员工/门店员工时没有把父列表的 `dataset_epoch` 和 `data_version` 带到该端点的首页请求。触发方式是在部门/门店列表读完后、关联员工请求开始前发生一次发布；页面会同时展示不同版本的树、门店和人员归属，而后端无法返回预期的 409。`docs/backend-api.md:16-37,65` 明确支持并要求跨端点传版本。应让关联查询携带父资源 meta，并在版本冲突时把整个页面关联资源作为一轮重新读取，而非只重试子端点。

4. `frontend/src/components/AuthGate.tsx:11-29`、`frontend/src/services/http.ts:38-44`：身份门禁只检查初始 session，请求层没有全局 401/403 通知或状态；会话在工作台打开期间被撤销、白名单被删除或过期后，业务读取仅由 `ResourceState` 显示“读取失败”，写请求仅 toast，工作台和敏感操作仍留在屏幕。触发方式是登录后使 session 失效再读取或写入；影响是“全局处理 401/403”未实现，权限状态与界面状态不一致。应由请求层发布鉴权失败，交给 AuthGate 重新验证并切换到登录/无权限页，同时清除内存 CSRF token。

5. `frontend/src/pages/LogsPage.tsx:4` 与 `docs/backend-api.md:61`：日志页没有“操作”筛选，也没有结束时间；却发送契约未声明的 `actor`、`committed_after` 参数，并把 Ant Design `DatePicker` 值直接 `String()` 化，而不是契约化的 UTC ISO 8601。触发方式是按操作者或开始时间查询；后端若严格校验会返回 422，若忽略未知参数则界面显示已筛选但结果未筛选。规格要求对象、操作、操作者、任务、时间均可过滤。应先统一后端契约，再按明确字段发送操作、操作者、起止 UTC 时间，并增加交互测试验证 URL。

6. `frontend/src/pages/OrganizationPage.tsx:19-22`：搜索通过删除不匹配节点后重建树，但保留祖先的判断方向错误；它检查“当前节点 path 是否包含命中节点 id”，通常无法让祖先命中，命中节点因父节点缺失会被提升为根。触发方式是搜索任一深层部门；结果不再定位于原树层级，也无法展示祖先路径，偏离“搜索定位树”。应从每个命中项的 path/父链收集祖先 ID，再用该集合过滤并展开/高亮命中节点，并用至少三层树交互测试覆盖。

7. `frontend/src/styles.css:1`、`frontend/src/pages/OrganizationPage.tsx:22`：窄屏媒体规则仅把两列改成单列，部门树仍永久占据页面且没有进入 Drawer。触发方式是在小于 900px 的视口打开组织页；用户需先滚过完整树才能看到人员表，未实现明确要求的“窄屏树进抽屉”。应在窄屏提供打开部门树的按钮和受控 Drawer，并保留选择、搜索和独立勾选状态。

8. `docs/superpowers/task-3-report.md:35-41`：实施报告明确写着“浏览器端真实业务交互未在本任务中验收”，而任务要求记录浏览器验证证据。当前测试主要覆盖请求层、分页、资源竞态、AuthGate 和两个纯领域函数；没有覆盖批量勾选→预览→内容改变失效→409 保留→重新预览→提交这条核心交互。构建和 12 项测试通过不能替代这项验收。应补真实组件交互测试，并在可用后端或受控测试后端上记录 1080/1440/窄屏浏览器验证；Task 2 接口未就绪的部分可继续明确标为跨任务未验证。

9. `backend/app/persistence/read_service.py:163,174,181`、`frontend/src/domain.ts:2-4,16`、`frontend/src/pages/OrganizationPage.tsx:24`、`frontend/src/pages/StoresPage.tsx:8`：真实读服务把状态输出为 `status: "active"|"inactive"`，但前端 `isActive` 只读取布尔 `active/is_active`，字段不存在时默认 `true`。触发方式是加载任一失效部门、门店或员工；失效门店会显示“有效”，失效员工会显示“在职”，直接误报飞书事实状态。1080×900 Edge 后端形状夹具已复现。应统一领域类型与后端字段，并让未知状态显式显示未知，不能默认有效。

10. `backend/app/persistence/read_service.py:177-181`、`frontend/src/domain.ts:3`、`frontend/src/pages/EmployeePage.tsx:9`：后端员工详情返回 `department_ids`、`primary_department_id`、`store_ids` 和 `primary_store_id`，前端却只渲染 `departments`、`stores` 这两组对象数组以及可选 `primary_store` 对象。触发方式是打开具有部门和门店归属的员工；页面会显示“暂无部门关系”“不在任何门店”，虽主门店 ID 可能偶然显示。Edge 夹具已复现。应在 `docs/backend-api.md` 固化一种响应结构并同步两端；若使用 ID 数组，前端需显示并标注主部门，若使用对象数组，后端需返回稳定的对象结构。

11. `backend/app/persistence/read_service.py:156-163`、`frontend/src/components/StoreEditor.tsx:10,13`：组织页部门对象不含 `notes`，但编辑器用该对象初始化备注。用户从组织树打开已有备注的门店时，备注框为空；一旦编辑并预览，表单会把空/未定义状态参与 change，存在把未加载的既有备注清空或产生错误预览的风险。后端 PATCH 契约规定省略表示保留、显式 null 表示清空（`docs/backend-api.md:67`），前端必须区分两者。应让部门读取返回 notes，或编辑前读取 `/admin/api/stores/{id}` 完整资料；未加载字段不得作为清空值提交。

12. `backend/app/persistence/read_service.py:32-35`、`frontend/src/pages/SyncPage.tsx:6`：状态接口返回 `initialization_status`，同步页却读取 `initialized ?? status`，因此即使后端返回 `initialization_status: "complete"` 也显示“未知”；Edge 夹具已复现。应按实际契约读取 `initialization_status`，并对 Task 2 将新增的连接状态、任务 phase/stage 与 attempt/attempt_count 字段做一次完整字段对表后再联调验收。

#### Minor (Nice to Have)

1. `frontend/vite.config.ts:8-12`：任务接口清单明确写了开发代理 `/admin`、`/api`、`/auth`，配置缺少独立 `/auth`。当前实际会话路径位于 `/admin/auth/**`，所以现有流程仍由 `/admin` 覆盖；若后续使用顶层 `/auth/**` 会直接落到 Vite。应补上该代理以匹配约定，或在规格中删除未使用的顶层路径。

2. `frontend/src/pages/SettingsPage.tsx:2,6`：页面使用静态 `message`，实施报告中的 Ant Design lint 也已报告上下文迁移警告；这可能丢失 ConfigProvider/App 的主题与上下文。应与 `StoreEditor`、`App` 一致使用 `App.useApp()`。

### Assessment

**Task quality:** Needs fixes

**Reasoning:** 基础请求和单端点分页处理质量较好，但门店预览后没有可达的提交路径、前后端核心读模型字段不兼容、批量操作会静默漏改、跨端点版本一致性没有建立，且权限失效、日志筛选和核心浏览器交互尚未闭环；这些问题修复前不能批准 Task 3。
