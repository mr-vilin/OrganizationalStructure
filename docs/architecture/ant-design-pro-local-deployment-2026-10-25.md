# Ant Design Pro 本机 Docker 部署记录

- 日期：2026-10-25（北京时间）。
- 目标：用户明确选择本机 Docker，Compose 项目 `organization-directory`。
- 结果：部署成功；app、MCP、MySQL 均 healthy，app / MCP 重启计数均为 0。
- 访问入口：<http://127.0.0.1:8000/organization>。

## 代码、构建与切换

通过 `git archive` 导出已提交的 `db5d9e5bc500dc4c5d76fcd7e07b5c1e97520fea` 单独构建，不使用带有未提交修改的工作目录。产品版本为 0.1.0、development、dirty=false、releaseDate=null，构建时间为 `2026-10-25T15:50:36.859Z`。它是开发部署，不是发行版本。

使用 Dockerfile 原有多阶段流程、严格 npm ci、类型检查和 Utoopack 构建；临时构建文件仅将官方 Node / Python 基础镜像改用公开 ECR 镜像源，仓库 Dockerfile 保持原地址。候选镜像 `organization-directory-runtime:pro-db5d9e5` 验证通过后同时标记为 `:local`，保持现有 Compose 默认标签。

运行镜像 manifest：`sha256:390ddfb126f66981f9d6b377a4f3687d16fec1b7d2d608939f17c3c9e3fefc53`。app 和 MCP 实际运行相同镜像，沿用原端口、网络与配置。

实际切换命令：

```powershell
docker compose --profile agent up -d --no-deps --no-build --wait --wait-timeout 120 app mcp
```

仅重建 app 和 MCP；没有启动 migrate、重建 MySQL、修改部署配置或远端服务。此前的[实施与隔离验收](ant-design-pro-migration-acceptance-2026-10-25.md)继续保留为构建和业务回归证据。

## 运行验证

| 检查 | 结果 |
| --- | --- |
| live / ready | 均 200，数据库和结构 ready |
| 页面深链接 | `/organization`、`/employees/e1`、`/sync?job=j1` 均返回页面 HTML |
| 静态资源 | 运行中服务的全部 31 个 JS/CSS 资源均 200，MIME 非 HTML |
| 缺失资源 / API | `/missing.js`、`/admin/api/missing` 均 404 |
| 未登录认证 | session 和版本接口均 401 |
| 构建元信息 | HTTP build-info、后端包完全一致，提交为 db5d9e5、dirty=false |
| 浏览器 | 本机页面实际显示飞书登录入口和重新检查按钮；控制台 error/warn 为空 |

数据库只读前后核对：MySQL 8.4.11、`0009_operation_receipt`、utf8mb4 / utf8mb4_general_ci、UTC、REPEATABLE-READ。部门、员工、员工部门关系、门店资料、操作回执、待核实事实仍均为 0；data_version=0，初始化 pending、覆盖 unknown。没有执行数据库迁移或人工业务写入。

本次提交的 worker 与 repository 文件 SHA-256 与切换前运行容器一致。未提交的队列修复没有进入镜像。原有两个任务仍为 queued，initialize 的 execution_count 仍为 0；旧 reconcile 仍处于 waiting_initialization 且持续认领，属于部署前已有问题，本次没有手工改队列或新增初始化。监听观察仍 degraded，不将容器健康等同飞书事件连接正常。

本机回调配置仍为 HTTP `127.0.0.1`，本次未修改认证配置、未进行真人飞书登录或登录后业务写入。HTTPS 企业登录和真实业务流程需要独立验收；没有改动腾讯云测试环境。

## 回滚

旧镜像保留为 `organization-directory-runtime:pre-pro-20261025`，ID 为 `sha256:5544e4597f895aa1e2f029b3810515a0cb153e9f171d49918f257665b8ef5bf4`。回滚时恢复默认标签并仅重建相同服务：

```powershell
docker tag organization-directory-runtime:pre-pro-20261025 organization-directory-runtime:local
docker compose --profile agent up -d --no-deps --no-build --wait --wait-timeout 120 app mcp
```

本次无数据库结构变化，不需要数据恢复。回滚镜像保留原有同步队列行为。

忽略目录 `.cache/` 保存 `pro-local-deploy-build.log`、`pro-local-before.jsonl`、`pro-local-after.jsonl`、`pro-local-http-after.json`、`pro-local-resources-after.json` 和回滚镜像记录；不包含连接凭据。

![本机 Docker 实际登录页面](../ui/pro-migration-2026-10-25/local-deployment-login.png)
