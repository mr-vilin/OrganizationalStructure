# 组织服务实施任务计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans，按任务实施；用复选框跟踪完成情况。

**Goal:** 将组织服务方案实现为 Python + Ant Design + MySQL 的可部署系统。

**Architecture:** FastAPI 提供管理与只读 API，React 管理页面同源访问。MySQL 保存事实、门店资料、会话、任务与审计；飞书通过适配器采集并事务发布。

**Tech Stack:** Python、FastAPI、SQLAlchemy、PyMySQL、Alembic、React、TypeScript、Vite、Ant Design、MySQL 8.4。

**Spec:** `docs/搭建计划.md`、`方案.md`、`同步与接口设计.md`、`决策与验收.md`。

## Global Constraints

- 一个实例连接一个飞书组织，使用独立 MySQL；所有业务表使用 InnoDB、utf8mb4。
- 飞书事实只读，本地仅维护门店标记、编码与备注；虚拟根不能设为门店。
- 每条部门关系向上找最近门店；主门店只从唯一飞书主部门派生，未知与不在门店分开。
- 缺页、权限收窄、一次查不到不等于离职或删除；失败保留已提交版本。
- 管理员白名单与只读 API 凭据分开鉴权；秘密不回显、不写日志。
- 事实、派生、日志和版本原子提交；无业务变更不增加版本。
- 跨页/跨端点使用同一世代及版本，变化返回 409，初始化未完成返回 503。
- 中文界面；测试用例围绕行为，真实 MySQL/飞书未验证的项明确保留未验收状态。

## 任务分解

### Task 1：后端领域、持久化、接口与权限

**Files:** `backend/pyproject.toml`、`backend/app/`、`backend/migrations/`、`backend/tests/`。

**Interfaces:** 导出 `app.main:app`；环境变量 `ORG_DATABASE_URL`、`ORG_SESSION_SECRET`、`ORG_FEISHU_APP_ID`、`ORG_FEISHU_APP_SECRET`、`ORG_FEISHU_REDIRECT_URI`、`ORG_INITIAL_ADMIN_OPEN_IDS`。HTTP 数据 envelope 为 `{data, meta}`；错误为 `{error:{code,message}}`。管理写入附带 `X-CSRF-Token`。

- [x] 写领域行为测试：多部门、主部门、嵌套门店、失效、缺失祖先；先执行失败，再实现。
- [x] 写权限与分页测试：匿名 401、机器凭据不能写管理接口、游标签名及筛选绑定；实现会话和 API 凭据哈希保存。
- [x] 实现配置、MySQL 模型与 Alembic；读 API、部门/员工/门店查询、批量预览与修改、版本事务、日志、客户端及白名单管理。
- [x] 实现任务持久提交、复用、重试与状态 API，为 Task 2 保留清晰服务边界。
- [x] 执行 `python -m pytest backend/tests -q`，保存失败/通过证据与未验证项，输出前端接口说明。

核心行为示例：

```python
# 主部门在总部，兼职大学城店，不能把兼职门店充当主门店。
assert result.store_ids == ["university"]
assert result.primary_store_id is None
assert result.primary_store_status == "not_in_store"
```

### Task 2：飞书接入、采集与同步执行

**Files:** `backend/app/feishu/`、`backend/app/sync/`、`backend/tests/test_feishu*.py`、`backend/tests/test_sync*.py`。

**Interfaces:** 使用 Task 1 数据模型、会话工厂、发布锁和任务表；输出 worker 可执行入口与 OAuth 回调接入。

- [x] 查阅官方 SDK/接口，验证字段/ID 类型；写分页失败、缺失主部门、乱序事件和权限异常测试。
- [x] 实现 OAuth code 交换与登录身份映射，state 校验、白名单校验、组织身份校验。
- [x] 实现全量/子树分页采集、祖先补齐、事件持久化与回查、临时采集到原子发布；不可确认失效保留记录并标记质量。
- [x] 实现单 worker 租约、退避、重启恢复、每日北京时间 03:00 核对、长连接恢复核对。
- [x] 运行领域与适配器测试；记录真实企业授权与 MySQL 并发联调限制。

```python
# 失败采集不能覆盖旧数据。
assert after.data_version == before.data_version
assert after.employee_ids == before.employee_ids
```

### Task 3：Ant Design 管理端

**Files:** `frontend/package.json`、`frontend/src/`、`frontend/vite.config.ts`、`frontend/tests/`。

**Interfaces:** 消费 Task 1/2 的接口说明，Vite 将 `/admin`、`/api`、`/auth` 代理到本地后端；生产同域。

- [x] 查询 Ant Design 组件 API；建立 React/TypeScript/Vite、中文主题、路由和请求层。
- [x] 实现登录/无权限/未初始化页面，以及组织树、人员详情、门店、同步、日志和设置。
- [x] 接入真实接口，处理 loading、empty、error、409 冲突、CSRF 与任务轮询；独立树勾选、批量预览与提交。
- [x] 写交互测试并执行；`npm run build` 通过，无编译错误。
- [x] 输出操作指南与本地启动步骤，记录浏览器验证证据。

```typescript
// 保存按钮只能在预览与当前内容版本匹配后提交；冲突时保留表单并重新预览。
expect(screen.getByText('数据已更新，请重新预览')).toBeVisible();
```

### Task 4：部署、集成与验收

**Files:** `Dockerfile`、`compose.yaml`、`.env.example`、`deploy/`、`docs/运行与验收.md`、`README.md`。

**Interfaces:** 同一镜像提供静态页面、HTTP 和后台执行；MySQL 健康后执行迁移；配置不提交秘密。

- [x] 实现前端构建到 Python 镜像、多进程监督与健康检查、MySQL 持久卷。
- [x] 编写备份/恢复指令、世代重置与管理员恢复方式，提供本地运行步骤。
- [x] 运行全量后端测试、前端构建、迁移 SQL 检查；有 MySQL 时执行真实事务验证。
- [x] 进行任务审查及整体审查，修复重要缺陷；逐项记录 AC01～32 状态。

## 执行说明

当前目录无 Git 仓库，且 `.git` 在当前权限配置中只读；先在独立项目目录实施，保留任务台账，不伪造 Git 提交或 worktree。Docker 引擎当前不可达，部署与 MySQL 集成验证需在可用后补齐。未配置飞书秘密时页面明确提示配置缺失，拒绝伪造登录或同步成功。

## 完成边界

2026-09-15：上述复选项按用户“先完成代码、后提供数据库环境”的范围完成。后端95项、前端25项、部署5项通过；6项真实MySQL用例跳过。整体代码审查已通过。真实数据库/飞书权限与事件、Docker镜像启动和恢复演练仍未执行，具体逐项状态见 `docs/运行与验收.md`，不因计划勾选而视为企业验收通过。
