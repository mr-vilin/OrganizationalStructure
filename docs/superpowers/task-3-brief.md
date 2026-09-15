# Task 3：Ant Design 管理端

**Files:** `frontend/package.json`、`frontend/src/`、`frontend/vite.config.ts`、`frontend/tests/`。

**Interfaces:** 消费 Task 1/2 的接口说明，Vite 将 `/admin`、`/api`、`/auth` 代理到本地后端；生产同域。

- [ ] 查询 Ant Design 组件 API；建立 React/TypeScript/Vite、中文主题、路由和请求层。
- [ ] 实现登录/无权限/未初始化页面，以及组织树、人员详情、门店、同步、日志和设置。
- [ ] 接入真实接口，处理 loading、empty、error、409 冲突、CSRF 与任务轮询；独立树勾选、批量预览与提交。
- [ ] 写交互测试并执行；`npm run build` 通过，无编译错误。
- [ ] 输出操作指南与本地启动步骤，记录浏览器验证证据。

```typescript
// 保存按钮只能在预览与当前内容版本匹配后提交；冲突时保留表单并重新预览。
expect(screen.getByText('数据已更新，请重新预览')).toBeVisible();
```


## Global Constraints

## 前端落地细节

- 已安装前端依赖并生成 `frontend/package-lock.json`；使用 `npm.cmd --prefix frontend ...`，缓存参数指向项目内 `.cache/npm-frontend`，避免使用用户全局缓存。
- 前端基础已实现：`services/http.ts`（request/query/CSRF/ApiError）、`useResource.ts`（防旧请求覆盖）、`readAll.ts`（版本一致完整分页）、`components/AuthGate.tsx`（会话门禁）。当前 10 项测试和 TypeScript 检查通过；复用这些模块，确有改动需保留回归。会话接口 `/admin/auth/session`，退出 `/admin/auth/logout`。
- 本地 Ant Design CLI：`.tools/antd/node_modules/.bin/antd.cmd`。常用组件 JSON 资料已在 `.tools/antd/antd-*.json`，实现前读取对应属性与 demo。
- 参考 `docs/ui/01-organization.svg` 至 `06-settings.svg` 的布局与中文信息架构。直接使用真正 Ant Design 组件，不显示整张 SVG 冒充界面。
- 默认真实模式；未连接后端时显示连接失败/重试，未配置登录时显示配置缺失；不能自动登录或显示示例业务数据。
- 组织页：搜索定位树、独立勾选节点、直属/全部后代人员切换、门店编辑抽屉、批量预览确认；人员详情解释所有门店与主门店派生状态。
- 门店页：名称/编码搜索、包含失效筛选、编辑资料、查看全部/主门店归属员工；人数不可误加成企业人数。
- 同步页：健康状态与最近全量时间、任务列表、任务实际阶段/计数、详情与重试；未知总量不展示伪百分比。
- 日志页：过滤对象、操作、操作者、任务、时间与差异详情。设置页：白名单、客户端新增/轮换/撤销与一次性凭据展示、每日时间配置、脱敏连接摘要。
- 可提供**仅开发环境**显式开启的隔离演示适配器，必须醒目标注演示数据，且不得通过后端身份验证绕过；仅在时间允许且测试/浏览器验证需要时实现。
- 业务请求带 credentials、写请求带 CSRF；全局处理 401/403/409/503，显示可理解错误并保留输入。
- 页面可分页浏览全部数据，不仅显示服务默认第一页。树可以使用一致版本的全部部门拉取，遇 409 整轮重试并限制次数。
- 导航使用正规图标，1080/1440 宽度可用，窄屏树进抽屉、表格横向滚动；按钮有 loading 与防重复提交。


- 一个实例连接一个飞书组织，使用独立 MySQL；所有业务表使用 InnoDB、utf8mb4。
- 飞书事实只读，本地仅维护门店标记、编码与备注；虚拟根不能设为门店。
- 每条部门关系向上找最近门店；主门店只从唯一飞书主部门派生，未知与不在门店分开。
- 缺页、权限收窄、一次查不到不等于离职或删除；失败保留已提交版本。
- 管理员白名单与只读 API 凭据分开鉴权；秘密不回显、不写日志。
- 事实、派生、日志和版本原子提交；无业务变更不增加版本。
- 跨页/跨端点使用同一世代及版本，变化返回 409，初始化未完成返回 503。
- 中文界面；测试用例围绕行为，真实 MySQL/飞书未验证的项明确保留未验收状态。
