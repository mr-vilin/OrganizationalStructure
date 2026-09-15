# Task 3 实施报告：Ant Design 管理端

## 交付内容

- 建立 React 19、TypeScript、Vite、React Router、Ant Design 6 中文管理端入口和响应式应用壳。
- 实现五项主导航：组织架构、门店管理、同步中心、变更日志、管理设置，以及独立人员详情路由。
- 所有业务读取均访问真实 `/admin/api/**`；写请求复用会话 CSRF。列表通过版本一致分页读完整数据，409 时整轮重读，最多三次。
- 组织页支持树搜索、严格独立勾选、直属/全部后代人员切换、门店编辑预览和提交。表单内容或版本变化后提交按钮立即失效；apply 返回 409 时保留输入并显示“数据已更新，请重新预览”。
- 门店页支持搜索、失效筛选、全部/主门店归属员工以及编辑；两种人数均明确为门店归属人数。
- 同步页支持创建全量任务、稳定分页任务列表、详情、活动任务轮询和失败重试。总量未知时不计算百分比。
- 日志页支持对象、类型、来源、操作者、任务、时间条件和 before/after 差异抽屉。
- 设置页支持白名单新增/删除、API 客户端新增/轮换/撤销和一次性密钥强提示。
- 全局覆盖 loading、empty、error、401/403 门禁、503 未初始化与操作失败反馈；表格允许横向滚动，窄屏导航进入抽屉。

## Ant Design 依据

开发前使用项目内 CLI 查询了 Ant Design 6.6.4 的 `Layout`、`Tree`、`Table`、`Drawer`、`Form`、`Modal`、`Descriptions` 和 `Tabs` API。实现采用 `Tree.checkStrictly` 保证节点勾选互不联动，采用 `Drawer.destroyOnHidden` 和受控 `open` 属性，并使用 `Table.scroll.x` 支持窄屏。

## 后端需要补齐的契约

### 1. 同步健康摘要

扩展 `GET /admin/api/status` 的 `data`：

```json
{
  "connection": { "status": "connected|degraded|unconfigured", "checked_at": "UTC ISO 8601", "app_id_masked": "cli_***abcd", "tenant_key_masked": "t-***1234", "scopes": ["contact:department.base:readonly"] },
  "last_event_processed_at": "UTC ISO 8601 or null"
}
```

连接摘要只能包含脱敏标识和权限名，不返回 app secret、token 或其哈希。

### 2. 每日核对时间

- `GET /admin/api/settings/reconcile-schedule` 返回 `data: { "enabled": true, "local_time": "03:00", "timezone": "Asia/Shanghai", "updated_at": "UTC ISO 8601" }`。
- `PUT /admin/api/settings/reconcile-schedule` 使用相同 body（不含 `updated_at`），要求 CSRF；返回规范化后的完整设置。
- 非法 IANA 时区或时间返回 `422 VALIDATION_ERROR`；更新写入审计日志。调度器应以该时区解释本地时间，并明确 DST 行为。

在这些接口落地前，前端相关标签页只显示缺失提示，不模拟连接状态或保存成功。

## 验证

- `npm.cmd --prefix frontend test -- --run`：通过，5 个测试文件、12 项测试全部通过。
- `npm.cmd --prefix frontend run build`：通过，TypeScript 与 Vite 生产构建成功；Vite 提示主包约 1.28 MB，可在后续按页面懒加载优化首屏体积。
- `.tools/antd/node_modules/.bin/antd.cmd lint frontend/src --format json`：命令通过；无可访问性或性能问题，仍报告 Ant Design 6 的迁移建议（静态 message 上下文、Alert/Drawer/List 废弃项），不影响类型检查或构建。

真实 MySQL、飞书 OAuth、通讯录授权范围、远程同步和浏览器端真实业务交互未在本任务中验收；无后端时身份门禁会如设计显示连接错误及重试入口。

## 修复轮 1

逐项处理 `task-3-review.md`：

1. 批量设置现向编辑器传入全部独立勾选部门，preview/apply 均提交完整 `changes`。
2. 确认按钮移入预览 Modal；“返回编辑”保留有效预览和输入。
3. 部门员工、门店员工首请求携带父资源 `dataset_epoch/data_version`；409 会刷新父资源基准。
4. 请求层在业务请求收到 401/403 时清除 CSRF 并通知 AuthGate 重验会话，敏感业务树随门禁卸载。
5. 日志增加 action、actor、起止时间和重置；时间以 `toISOString()` 发送 UTC。
6. 树搜索沿父链保留祖先、展开结果并高亮命中节点。
7. 小于 900px 时隐藏常驻树，以“选择部门”按钮打开 Drawer，选择后关闭并保留搜索、勾选和选中状态。
8. 新增真实 StoreEditor 交互测试，覆盖完整批量 preview/apply 和 409 保留输入；请求测试覆盖鉴权失效通知。
9. 领域模型改用后端真实 `status: active|inactive`，未知状态明确显示“未知”。
10. 人员详情使用后端真实 `departments/stores/primary_department_id/primary_store_id` 结构。
11. 部门读取已包含 notes；编辑器保留各部门原编码与备注，且使用 `is_virtual_root` 禁止虚拟根标记。
12. 同步中心读取 `initialization_status`、`connection`、`last_event_processed_at`，按 `phase/attempt/progress` 展示任务；接通事件列表及安全重试，并为缺少对象 ID 的事件解释不可重试原因。
13. 设置页接通每日核对 GET/PUT，固定提交 `Asia/Shanghai`，使用后端返回值回填。
14. 补充 Vite `/auth` 代理，静态 message 改用 `App.useApp()`，清除 Ant Design 6 lint 警告。

部署文档补充了 Bash 恢复的实际导入顺序，但未执行恢复演练。

修复轮最终验证：

- `npm.cmd --prefix frontend test -- --run`：6 个测试文件、15 项测试全部通过。jsdom 对伪元素 `getComputedStyle` 输出非阻断提示。
- `npm.cmd --prefix frontend run build`：TypeScript 与 Vite 构建通过。主 JavaScript 包约 1.28 MB，Vite 仍建议后续按页面拆包。
- `.tools/antd/node_modules/.bin/antd.cmd lint frontend/src --format json`：0 issues，deprecated、a11y、usage、performance 均为 0。
- 浏览器端 1080、1440 和窄屏复验由根任务使用受控夹具执行；本报告不提前声明该项通过。

## 修复轮 2

- 编辑器草稿初始化只发生在关闭到打开的新会话；apply 409 后父列表即使返回全新的部门对象，也不会覆盖用户草稿。重新预览使用刷新后的版本，并继续提交完整批量 changes。
- 组织与门店关联员工请求增加原子前置条件：父数据、epoch、version 全部就绪才会发请求。子请求持续发生 `DATASET_CHANGED` 后触发父资源重读，父 meta 清空阶段子 path 为 null，避免无版本请求和混代短暂渲染。
- 无搜索时完全省略 Tree 的 `expandedKeys` 属性，恢复手动展开；搜索时保留祖先并受控展开，清空后回到可手动操作状态。
- 日志的飞书来源值修正为后端真实枚举 `feishu`。新增真实组件测试，覆盖 source/action/actor 请求参数和重置。
- 恢复 Bash 块增加 `set -euo pipefail`；在明确目标、停止应用且目标现状备份成功后，显式删除并以 utf8mb4/utf8mb4_bin 重建 `organization`，再导入、迁移、生成新世代和重启核对。

修复轮 2 验证：

- `npm.cmd --prefix frontend test -- --run`：8 个测试文件、18 项测试全部通过。新增父子版本协调、三级树搜索/操作、真实日志筛选、真实父刷新后的批量草稿重预览测试。
- `npm.cmd --prefix frontend run build`：TypeScript 与 Vite 构建通过；仍有约 1.28 MB 主包体积建议。
- `.tools/antd/node_modules/.bin/antd.cmd lint frontend/src --format json`：0 issues。

## 修复轮 3

- 固定 `dataset_epoch/data_version` 的子列表首次收到 409 时立即退出分页读取，由组织页或门店页重读父基准；整组自动恢复设有上限，持续冲突会停止并提供可重置预算的手动重试，期间不会发送无版本子请求。
- 批量编辑的 preview 与 apply 409 均保留全部草稿、清除旧预览并刷新父版本。父页面集成测试覆盖两项勾选、备注修改、apply 409、父列表升级、按新版本再次 preview/apply 的完整流程；组件测试另覆盖首次 preview 409 后恢复。
- 补齐组织树真实折叠/展开、门店父子协调、日志 UTC 边界、持续冲突停止等交互测试。日志来源使用 `feishu`，对象枚举对齐 `admin_allowlist/event/security/settings/dataset` 等真实审计类型。
- 同步中心待处理事件改用真实 `queued`，覆盖不完整独立显示，并展示 `last_full_sync_at`；任务详情从活动态进入终态时自动刷新任务列表、状态摘要和事件列表。
- 人员详情展示员工及各部门同步质量、部门完整路径和门店派生 `path_names`；`pending_verification` 明确提示保留旧资料待核实。
- 窄屏限制 Layout、Card 与表格外层最小宽度，Card 标题和操作区允许换行。390×844 Edge 夹具验证组织页选中部门后 `document.documentElement.scrollWidth=390`，同一脚本的批量冲突、计划和人员契约检查均通过，无 pageerror。
- Settings 的计划表单标签页使用 `forceRender`，确保异步回填前 Form 已连接，消除 `useForm` 警告。

修复轮 3 最终验证：

- `npm.cmd --prefix frontend test -- --run`：9 个测试文件、24 项测试全部通过；仅 jsdom 输出不支持伪元素 `getComputedStyle` 的非阻断提示。
- `npm.cmd --prefix frontend run build`：TypeScript 与 Vite 生产构建通过；主包 1,278.47 kB，保留既有拆包建议。
- `.tools/antd/node_modules/.bin/antd.cmd lint frontend/src --format json`：0 issues。
- `node C:/Users/Vilin/AppData/Local/Temp/org-ui-fixed-check.cjs`：batch-conflict、schedule、employee-contract、mobile-tree 四项全部通过；唯一控制台 warning 是夹具刻意返回的 HTTP 409。

## 最终限定修复

- 同步中心最近成功全量时间改为读取真实 envelope 的 `status.meta.last_full_sync_at`。
- 任务详情轮询按任务 ID 保存最后一个非空状态；`useResource.reload` 清空 data 的加载空档不会抹掉活动态。任务从 queued/running 进入 succeeded/failed 后自动刷新 status、jobs、events 三组资源。
- 日志对象类型补充后端真实 `membership`，并保留 `admin_allowlist`；组件测试验证两项均可选择。

最终限定验证：

- `node C:/Users/Vilin/AppData/Local/Temp/org-ui-sync-check.cjs`：通过。真实 meta 时间显示、150ms detail loading 空档、终态后三组资源刷新、queued 事件筛选与失败事件重试入队均通过；无 pageerror。
- `npm.cmd --prefix frontend test -- --run`：9 个测试文件、25 项测试全部通过。
- `npm.cmd --prefix frontend run build`：通过；主包 1,278.57 kB，仍只有既有拆包建议。
- `.tools/antd/node_modules/.bin/antd.cmd lint frontend/src --format json`：0 issues。
