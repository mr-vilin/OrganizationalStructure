# MCP 分支整合与本机部署验收

日期：2026-10-24。范围为本机 OrganizationalStructure，不包含云端发布、真实模型自主任务或企业飞书数据覆盖验收。

## 整合决定

- 将 `codex/agent-native-impl`（`35bd406`）合入本地 `main`，保留主分支 `2bd04a5` 已有的数据库整改、只读就绪检查、管理员会话摘要及测试库隔离。
- 保留 MySQL 8.4、InnoDB、`utf8mb4_general_ci`；稳定 ID/业务键仍为 `utf8mb4_bin`。未采用实现分支旧的 `0900_as_cs` 会话和新表默认值。
- 实现分支尚未发布的 `0007_operation_receipt` 调整为 `0009_operation_receipt`，接在 `0008_session_digest` 后，避免两个 Alembic head。旧独立工作树的测试库保持原状，不直接接入新构建。
- `0009` 仅新建 `operation_receipt`：19 列均有中文注释、显式引擎/字符集/排序规则、既有设计的唯一键与索引，无外键。保留所有既有表、列、索引、默认值、注释、约束及数据。
- 保留可选 MCP sidecar、分离令牌、受信主体、生产人工确认、幂等与版本冲突保护。MCP 只调用内部 HTTP，不获取数据库或飞书凭据。
- Docker `internal` 网络实测不发布宿主机端口。默认 HTTP sidecar 继续只在能力私网内运行；本机客户端使用官方 SDK 的 stdio 传输，通过 `deploy/mcp-stdio.ps1` 启动容器内进程。没有开放公网端口或放宽 Host/Origin 校验。
- 产品能力版本更新为 `v2.8.63`；技术包版本不变。

## 执行前检查与部署步骤

1. 核实当前 Compose 项目为 `organization-directory`，业务 MySQL 为本机 `127.0.0.1:13307` / `organization` / MySQL 8.4.11，迁移 `0008_session_digest`；核实实际会话为 utf8mb4、general_ci、UTC、RR。禁止将独立测试 URL 用于此部署。
2. 在独立 tmpfs MySQL 中完成全量迁移、业务评测及 `0008→0009→0008` 演练，验证升级只新增回执表，原表结构与合成管理员会话完全保留。
3. 构建最终镜像并记录镜像 ID。停止现有 app（HTTP、worker、监听一起停止），核实没有其他业务写入方，再保存原 21 张业务表的完整结构、行数与聚合行指纹；不记录会话值或连接凭据。
4. 使用 `mysqldump --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces` 备份。在内存中以当前 Windows 用户 DPAPI 加密，保存到 Git/Docker 忽略且 ACL 受限的 `backups/mcp-integration-20261024/`。不落地明文 SQL。
5. 在同一本机实例的新建临时 `_test` 库中恢复该备份，比较全部旧表结构和行指纹；对恢复副本执行真实 `0008→0009`，核实既有表和数据未变。恢复副本通过后才对 `organization` 执行迁移。
6. 为 MCP 和内部能力分别生成独立随机令牌，保留既有 `.env` 其他配置；固定 production/human_agent 身份。令牌只写受限本地配置，不进入参数、报告、Git 或镜像。
7. 执行一次性 migrate，成功后重建 app，并显式启用 `--profile agent` 的 mcp。保留原镜像和加密备份以供恢复。
8. 核验 0009 完整结构、原数据指纹、实际连接配置、三个应用子进程、应用/MCP 健康状态。通过官方客户端验证状态读取、15 工具、双协议模式、鉴权、Host/Origin 与拒绝写入。拒绝写入前后回执、任务、业务版本保持一致。
9. 验证本机 stdio 客户端可发现工具、读取状态、实际发起并拒绝人工确认；不以程序自动批准真实业务写入。验证后删除本次临时恢复库和隔离验收容器，不删除业务卷或原独立开发工作树。

## 失败恢复

- 构建或隔离验收失败：不停止当前 app，不执行业务库迁移。
- 备份或恢复副本校验失败：保持业务库在 0008，不执行 0009；恢复原 app。
- 新表 DDL 失败：MySQL DDL 不是事务回滚。先检查 Alembic 版本、新表完整定义及行数；禁止 stamp、盲目重试或清空已有表。
- 已成功升级但新应用不可用：停止全部新写入方，确认回执表无需要保留的操作后，使用受审查的 `0009→0008` 降级移除本次新表并恢复原镜像。若已有真实操作回执，先保留证据并单独制定恢复方案，不直接删表。
- DPAPI 备份只能由具有原 Windows 用户密钥的环境解密。全库恢复先停写、核实目标与结构，再按既有恢复规程撤销恢复出的凭据并核验数据世代，不能把旧管理员会话重新当成有效凭据。

## 验证进度

- 完整后端与部署回归：1326 passed、0 failed、0 skipped；日志位于 `.superpowers/runtime/mcp-integration-20261024/final.txt`。新增 stdio 入口后另行运行相关回归。
- 实际 MySQL 8.4.11 测试库：0009、22 张 ORM 表、结构检查零差异；会话 utf8mb4/general_ci、UTC、RR。
- 前端版本页测试通过，TypeScript/Vite 构建通过，Ant Design 6.6.4 查询及 lint 零问题。
- 独立容器 HTTP 验收通过：官方 MCP Client → MCP 容器 → 内部 HTTP → MySQL；legacy/auto 双模式、15 工具、后台状态、错误令牌、Host/Origin、真实 elicitation 拒绝全部通过。拒绝后操作回执/同步任务均为 0。
- MCP 容器没有 `ORG_DATABASE_URL`，连接 mysql 服务失败，符合网络隔离要求。隔离 app 仅启动 HTTP，生产监督器另在本机业务部署中核实。
- stdio 入口增量回归：`deploy/tests/test_mcp_runtime.py` 22 passed；包括 legacy/auto 两种真实进程发现。测试与前述全量有重叠，不相加作为总数。

## 本机实际部署结果

2026-10-24 20:51（北京时间）完成本次本机切换，所有必要命令退出码为 0。

| 项目 | 实际结果 |
| --- | --- |
| 目标 | Compose `organization-directory`，本机 `127.0.0.1:13307` / `organization`，MySQL 8.4.11 |
| 迁移 | `0008_session_digest → 0009_operation_receipt`，22 张 ORM 表，结构检查 0 差异 |
| 数据保留 | 停写后原 21 张表的完整结构、行数和聚合行指纹全部一致；新增回执表为空 |
| 加密备份 | `backups/mcp-integration-20261024/organization.sql.dpapi`，33,838 字节；配置另存 `env.before.dpapi`，目录与 `.env` ACL 仅当前 Windows 用户和 SYSTEM |
| 恢复验证 | 内存解密，恢复副本与原 21 表结构/数据一致；副本实际升级到 0009 后仍完全保留原表与数据；临时恢复库已删除 |
| 最终镜像 | `sha256:5544e4597f895aa1e2f029b3810515a0cb153e9f171d49918f257665b8ef5bf4`，app/migrate/mcp 共用 |
| 旧镜像 | `organization-directory-runtime:pre-mcp-20261024`，原镜像 `sha256:e2688f65aa9a54211ba1c92d71dcff80a46312d2343b1640f20fdcd386eece71`；保留以供恢复 |
| 容器 | app、mysql、mcp 均 running/healthy；检查时 app/mcp 重启计数均为 0 |
| 应用进程 | 监督器与 HTTP、同步 worker、飞书 listener 三个必要子进程均运行 |
| 实际运行会话 | performance_schema 按客户端 PID 核实 HTTP/worker/listener：utf8mb4、general_ci、`+00:00`、REPEATABLE-READ |
| HTTP | `/`、`/health/live`、`/health/ready` 均 200；未认证 `/admin/auth/session`、`/internal/capabilities/status` 均 401 |
| 页面产物 | 实际容器返回的前端 bundle 包含 `v2.8.63` |
| MCP HTTP | 真实容器官方客户端 legacy/auto 均通过；完整 15 工具、后台读取、独立令牌、Host/Origin、实际人工拒绝均通过 |
| 本机 MCP stdio | Windows `powershell.exe → deploy/mcp-stdio.ps1 → docker compose exec → 官方 stdio → 内部 HTTP → MySQL`，legacy/auto 均通过 |
| 隔离 | MCP 无 `ORG_DATABASE_URL`，不能连接 mysql；没有发布 MCP 宿主机端口，官方探针返回 `MCP_READY` |
| 拒绝副作用 | HTTP/stdio 所有合成申请均明确 decline；实际操作回执仍为 0，未手工触发同步或修改门店 |
| 业务状态 | 初始化仍 `pending`、data_version=0、覆盖 `unknown`；没有把服务运行当作组织数据已初始化 |

本次配置独立随机 MCP/内部能力令牌，保留既有数据库、飞书、会话等配置。完整台账、加密备份及脱敏测试日志留在本机；不将凭据、备份或私有运行资料加入 Git。隔离验收 Compose 与本次独立 tmpfs 测试实例验收后清理，原实现工作树与既有便携测试环境保留。

真实 Provider 自主调用、企业飞书覆盖、HTTPS 登录与真实业务写入的人工批准仍需独立验收；本次只验证真实确认请求及拒绝路径，没有自动批准真实业务操作。未推送、未创建 PR、未做云端发布。
