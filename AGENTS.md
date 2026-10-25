# 项目开发规则

## 适用范围与依据

- 本文件适用于 OrganizationalStructure 仓库的全部开发、审查和交付工作。
- 本文件记录已确认的技术选型与开发约束；实际安装版本以依赖清单、锁文件和运行环境为准。
- `docs/搭建计划.md` 保留历史设计背景，其中“推荐”“建议”和旧环境状态不代表当前可自由替换的技术选型。
- 修改既定框架、数据库、构建工具或部署拓扑前，先说明原因、兼容性、影响范围和迁移方案，并取得用户确认；已获当前任务明确授权的变更按授权范围执行。

## 技术栈

| 层面 | 已确认技术与约束 |
| --- | --- |
| 前端语言与框架 | React、TypeScript |
| 管理端方案 | **Ant Design Pro v6** |
| 基础组件库 | Ant Design 6（`antd`）、`@ant-design/icons` |
| 当前构建与路由 | Umi Max 4.7、Utoopack；应用路由由 Umi 配置维护（2026-10-25 按迁移方案获准替换 Vite / 手写 React Router） |
| 后端 | Python、FastAPI、Pydantic / pydantic-settings、Uvicorn |
| 数据访问与迁移 | SQLAlchemy 2、PyMySQL、Alembic |
| 数据库 | MySQL 8.4、InnoDB、`utf8mb4`；当前 Compose 排序规则为 `utf8mb4_general_ci`，稳定 ID 字段保留 `utf8mb4_bin`（2026-10-22 已确认） |
| 飞书集成 | 官方 `lark-oapi` Python SDK、HTTPX；接口和权限按实际企业配置验证 |
| 测试 | 后端 pytest；前端 Vitest、Testing Library；关键浏览器流程按需验证 |
| 构建与交付 | Docker 多阶段构建、Docker Compose；当前镜像使用 Node.js 24 构建前端、Python 3.13 运行后端 |

### Ant Design Pro v6 的实施边界

- 管理端采用官方 Ant Design Pro 6.0.3 固定快照的工程约定；Umi Max `4.7.23`、ProComponents `3.1.14-2`（预发布）与 Ant Design `6.6.4`。迁移及验证边界见 `docs/architecture/ant-design-pro-migration-acceptance-2026-10-25.md`。
- Ant Design Pro、Ant Design（`antd`）和 ProComponents 是不同项目，版本号不能相互替代；不得根据“Pro v6”推定 `@ant-design/pro-components` 应安装 6.x。
- 升级 Umi / ProComponents 时检查定向 overrides、严格 peer 安装、类型检查与生产异步资源；`react-router-dom` 直接依赖只供 Vitest 导航边界使用，生产页面从 `@umijs/max` 导入导航。
- 编写或修改 Ant Design 组件前，使用 `antd` 技能及官方资料，按项目实际依赖版本查询 API，不凭记忆编造属性或套用其他版本示例。
- 管理端沿用中文界面；页面文案、字段位置和已确认交互作为验收依据。

## 目录与部署边界

- `frontend/` 存放前端工程，`backend/` 存放后端工程，`deploy/` 存放部署入口和运行工具。
- 开发模式：前端 Umi Max 默认端口为 `5173`，后端默认端口为 `8000`；前端通过代理访问后端接口。
- 当前 Docker 模式：前端构建产物打入 Python 应用镜像，由 `deploy/asgi.py` 提供页面和 API，共用 `8000` 端口；属于代码分离、合并部署。
- Compose 包含 `mysql`、一次性迁移服务 `migrate` 和应用服务 `app`；应用容器监督 HTTP、同步 worker、飞书事件监听进程。
- 不自行拆分为前后端独立容器，不自行引入 Redis、消息队列或其他基础设施；需要调整时遵循前述变更确认规则。
- 正式登录使用统一域名的 HTTPS 入口。登录入口与回调地址保持一致；不得通过关闭 state、CSRF 或会话安全校验修复登录问题。

## 依赖、验证与文档维护

- 前端依赖以 `frontend/package.json` 和 `frontend/package-lock.json` 为准，后端依赖以 `backend/pyproject.toml` 和 `backend/requirements.lock` 为准；更新依赖时同步维护相应锁文件。
- 数据库规范同时适用于建表 SQL、迁移、ORM 和连接配置。变更前核实目标环境的实际结构与会话设置；生成迁移脚本不代表获得真实数据库执行授权。
- 按变更范围运行相关测试和构建；单元测试、静态配置、离线迁移 SQL 不能替代真实 MySQL、飞书或运行容器验证。
- 报告时区分已实现、已验证、待接入和环境阻塞，不把历史验收记录当作当前环境证据。
- Windows 下读取中文文本显式使用 UTF-8，Node.js 命令优先使用 `npm.cmd`；不输出数据库密码、应用密钥或会话凭据。
- 技术选型变化时同步更新本文件及相关说明；产品版本遵循 `docs/versioning.md`（SemVer 2.0.0）；`version.json` 是唯一产品版本声明，`CHANGELOG.md` 保存 Unreleased 和按版本组织的发行记录。日常 PR 不自动递增版本；0.x 破坏性变化和新功能增加 minor，修复增加 patch。合并前运行 `node scripts/versioning.mjs check`；不得把开发基线、历史验收或构建通过描述为已经上线。
