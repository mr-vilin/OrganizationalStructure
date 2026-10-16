# 部署说明

## 准备配置

在项目根目录将 `.env.example` 复制为 `.env`，填写随机数据库密码、至少 32 字符的会话密钥、飞书企业自建应用信息和同应用初始管理员 `open_id`。数据库 URL 的密码与 `MYSQL_PASSWORD` 一致。部署地址需要 HTTPS，登录回调固定为 `/admin/auth/callback`。

`.env` 不进入镜像或版本控制。MySQL 容器不映射公网端口，应用默认仅监听宿主机 `127.0.0.1:8000`，由部署方的 HTTPS 入口转发。

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
# 用本机编辑器填好 .env 后执行：
docker compose up -d --build
docker compose ps
```

Compose 先等待 MySQL 就绪，再运行 Alembic 迁移，迁移成功后启动应用。应用进程监督器负责 HTTP、同步 worker 与飞书长连接三个独立进程；任一必要进程意外退出时终止其余进程，由容器重启恢复。长连接回调仅快速持久入箱，远程回查由 worker 执行；启动和断线恢复后安排全量核对。

## 飞书应用配置

1. 配置通讯录部门和员工基础资料读取权限、主部门字段权限、全员通讯录范围与管理员登录权限。
2. 订阅 `contact.department.created_v3`、`contact.department.updated_v3`、`contact.department.deleted_v3`、`contact.user.created_v3`、`contact.user.updated_v3`、`contact.user.deleted_v3` 及 `contact.scope.updated_v3` 七类事件。scope 更新事件用于立即使覆盖验收失效，必须实际订阅。
3. 启用长连接；应用服务器允许出网访问飞书。登录重定向地址与部署 URL 保持一致。
4. 使用实际授权样本验证根节点、无部门人员、全部分页和 `orders` 主部门标识，不将 SDK 字段存在当作企业联调完成。
5. 首次登录必须属于受控初始白名单；禁止首个访问者自动成为管理员。

## 一致性备份

业务运行期间不执行数据库 DDL。下列命令示例在 Bash 环境执行；密码由容器内部环境传入，不打印秘密到日志：

```bash
mkdir -p backups
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces organization' > backups/organization.sql
```

备份文件包含员工资料、会话哈希和审计信息，应使用受限存储并加密备份。配置与密钥独立备份；备份轮换由部署方的受控任务实施。

## 恢复演练

恢复操作覆盖目标库，只在明确选择的恢复环境执行，并先停止应用。先保留目标库现状备份，再导入备份文件。恢复后、重新开放读 API 前必须：

- 生成新的 `dataset_epoch`，禁止沿用备份中的旧世代。
- 撤销旧会话，重新核验管理员资格。
- 撤销备份恢复出的所有 API 凭据，避免已撤销凭据重新生效；重新生成并分发给下游。
- 全量核对飞书，并确认本地门店标记、编码保留与备注。
- 让下游按新世代重新拉取完整一致版本。

导入完成且应用已停止后，执行以下命令完成上述世代与凭据重置（不执行备份导入）：

```powershell
docker compose stop app
docker compose run --rm --no-deps app python -m deploy.recovery --application-stopped --actor "恢复责任人"
docker compose up -d app
```

该命令以单事务重置世代、隔离旧事件与未完成任务、撤销 OAuth state/会话/API 凭据，并写审计。门店资料与来源事实保留；初始化变为 pending，全量核对成功前读取数据返回 503。责任人参数必须填写实际标识。

如果备份中已无可用管理员，可在该命令中明确追加 `--admin-open-id ou_实际标识`，把经线下核验的同应用人员加入白名单并写审计。环境变量中的初始白名单只在首次初始化生效，重启不会自动恢复被删除的管理员。

真实 MySQL 恢复演练尚未执行，不将本说明视为恢复已验证。

### Bash 完整恢复导入顺序

以下是需要人工核对恢复环境和备份文件后执行的操作顺序示例。不要在生产环境未经审批直接运行；`BACKUP_FILE` 与目标 Compose 项目必须先由恢复责任人确认。

```bash
set -euo pipefail

# 1. 停止应用，避免导入期间产生写入
docker compose stop app

# 2. 明确并检查目标与输入文件
BACKUP_FILE="backups/organization.sql"
test -f "$BACKUP_FILE"
docker compose ps mysql

# 3. 导入前备份目标库现状
mkdir -p backups/pre-restore
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces organization' > "backups/pre-restore/organization-$(date +%Y%m%d-%H%M%S).sql"

# 4. 覆盖操作：仅在恢复责任人确认目标库为 organization 且上一步现状备份成功后，清空并重建目标库
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -e "DROP DATABASE IF EXISTS organization; CREATE DATABASE organization CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;"'

# 5. 导入已确认的 MySQL 备份
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot organization' < "$BACKUP_FILE"

# 6. 执行当前版本迁移
docker compose run --rm --no-deps app alembic upgrade head

# 7. 生成新世代，撤销恢复出的会话/API 凭据并写审计
docker compose run --rm --no-deps app python -m deploy.recovery --application-stopped --actor "恢复责任人"

# 8. 重启并核对；全量核对成功前业务读取应保持 503
docker compose up -d app
docker compose ps
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

重启后由管理员创建全量同步任务，确认新 `dataset_epoch`、初始化完成、覆盖验收状态和门店资料，再通知下游重新全量拉取。

## 数据库集成测试

Agent Evaluation 使用通用 Python 模块入口，默认串行。先准备独占、可清空的 MySQL 8.4 `_test` 库，字符集与排序规则为 `utf8mb4` / `utf8mb4_0900_as_cs`；按[测试迁移与评测命令](../docs/运行与验收.md#agent-evaluation-测试迁移与命令)核实实际目标并迁移。不要把已有生产环境的 `ORG_DATABASE_URL` 带入迁移进程。

从仓库根目录执行（凭据通过受控环境注入 `ORG_TEST_DATABASE_URL`，不要写入命令、报告或 Git）：

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation deploy/tests/test_evaluation_runtime.py -q
backend/.venv/Scripts/python.exe -m app.evaluation.cli --suite smoke --output .superpowers/evaluation-reports
```

CLI 的 `--case ORG_AGENT_VERSION_CONFLICT` 可筛选单例；退出码 `0` 为全部硬门槛通过、`1` 为硬断言失败、`2` 为配置/迁移/环境安全失败。没有实际 `_test` MySQL 不会降级为 SQLite 或模拟成功。报告为脱敏 JSON/中文 Markdown，软评分不改变退出码。脚本 Worker 与 Fake Feishu 用于普通 CI；真实模型、企业飞书和 Docker 运行分别验收。

`compose.mysql-test.yaml` 是可丢弃的独立本机测试环境，使用公开的测试密码和 tmpfs，不用于正式部署。它显式设置数据库 `utf8mb4` / `utf8mb4_0900_as_cs`，仅绑定 `127.0.0.1:13306`，库名必须以 `_test` 结尾。

迁移前检查、凭据文件格式、隔离环境的执行命令及 2026-10-15 便携 MySQL 8.4.11 的真实结果见[能力与观察层验收](../docs/运行与验收.md#能力与观察层验收2026-10-15)。Docker daemon 本轮仍不可用；便携 MySQL 的 18 项集成通过不代表 Docker、企业飞书或生产部署已验收。

## 内部能力服务与 sidecar 边界

内部端点前缀为 `/internal/capabilities`。部署时配置独立随机 `ORG_AGENT_SERVICE_TOKEN` 和 `ORG_AGENT_ENVIRONMENT=production`（隔离测试实例用 `test`）。令牌留空、错误或重复身份头均拒绝；只读 API 密钥、管理员 Cookie 和 CSRF 令牌不能替代此令牌。业务数据库仍由 `ORG_DATABASE_URL` 指向，运行时还需原有 `ORG_SESSION_SECRET`；服务令牌不得进入前端构建、浏览器、URL、访问日志或业务回执。

sidecar 直接通过受控的容器私网连接后端，生产端口继续仅映射宿主机回环地址。只有持有该令牌的受信 sidecar 能声明 `X-Agent-Actor-Type`、`X-Agent-Actor-Id`、`X-Agent-Environment`、可选 `X-Agent-Run-Id` / `X-Agent-Case-Id` 和 `X-Agent-Approved`。这些头代表受信服务的声明，部署者必须在 sidecar 验证调用者身份、权限和人工批准，再重新构造；不得透传浏览器可控头。production 写操作要求明确 `X-Agent-Approved: true`；CI 仅允许 `test` 环境、`_test` 实际数据库和 `test-` / `test_` 前缀的 run_id。

共享服务令牌不提供逐用户授权；不要把不可信客户端放入这个网络。外部 HTTPS 入口必须拒绝整个 `/internal` 路径，不能仅靠没有公开链接或 CORS 隐藏它。例如 Nginx 在普通代理规则前配置：

```nginx
location = /internal { return 404; }
location ^~ /internal/ { return 404; }
```

以上是待部署的网络配置要求；本轮只验证代码与受控 HTTP 鉴权行为，没有部署真实 sidecar 或执行真实 Agent 调用。

# 覆盖权限重新验收

通讯录 scope 变更后，覆盖状态降为 unknown。具备部署主机及数据库配置权限的运维人员完成真实企业验收（已发布应用的全员权限、无部门员工覆盖）后，在 `backend` 目录执行：

```powershell
./.venv/Scripts/python.exe -m app.sync.coverage --reference "企业验收记录-2026-09-15-02" --actor "operator:运维人员" --all-members-verified --departmentless-verified
```

Linux 使用部署环境的 `python -m app.sync.coverage`，参数相同。沿用 `ORG_DATABASE_URL/ORG_SESSION_SECRET/ORG_FEISHU_APP_ID/ORG_FEISHU_TENANT_KEY`；执行前先迁移到最新版本（含 `0003_pending_fact`）。reference 应为验收编号/摘要，不得填写 token/secret。

CLI 将新依据、标记清除、审计与新全量核对任务同事务提交，返回 job_id。该命令不会把覆盖直接改为 complete；worker 后续采集成功才能恢复，旧在途采集不能恢复。无需修改或手工删除数据库行。此文档提供执行方式，本轮没有对真实环境执行。

## 可选 MCP Streamable HTTP 侧车

默认 `docker compose up -d --build` 不启动 MCP。需要时在受限 `.env` 中配置下表，再显式启用：

```powershell
docker compose --profile agent up -d --build mcp
docker compose --profile agent ps
docker compose --profile agent exec -T mcp python -m app.mcp.health
```

启动顺序为 MySQL → 迁移 → app 就绪 → mcp。侧车与 app 复用 `organization-directory-runtime` 镜像和现有 Dockerfile，独立执行 `python -m app.mcp --transport streamable-http`，不运行应用监督器。侧车仅加入 `internal: true` 的 `capabilities` 网络；app 同时加入原默认网络及能力网络，MySQL、迁移仍在原默认网络。侧车没有宿主机端口、数据库网络、数据卷或全量 `env_file`，仅逐项传递下表配置，不获得数据库、飞书或管理员凭据。构建上下文排除 `.env`、venv 和 `.superpowers` 私有运行/凭据材料。

| 配置 | 用途与默认值 |
| --- | --- |
| `ORG_MCP_HOST` | CLI 监听地址；本机默认 `127.0.0.1`，Compose 默认 `0.0.0.0` |
| `ORG_MCP_PORT` | CLI 监听端口，默认 `8001`，范围 1–65535 |
| `ORG_MCP_SERVICE_TOKEN` | 必填，MCP 入站独立 Bearer token，仅交给受信 MCP 客户端 |
| `ORG_AGENT_SERVICE_TOKEN` | 必填，侧车调用内部能力 HTTP 的共享 token，须与 app 一致且与 MCP token 不同 |
| `ORG_AGENT_ENVIRONMENT` | 必填且与 app 一致，`production` 或 `test`；Compose 默认 `production` |
| `ORG_MCP_CAPABILITY_BASE_URL` | 必填 HTTP(S) 能力服务 origin；Compose 默认 `http://app:8000` |
| `ORG_MCP_ACTOR_TYPE` | 必填，`human_agent` 或 `ci_agent`；production 拒绝 ci_agent |
| `ORG_MCP_ACTOR_ID` | 必填，可信 Agent 主体标识 |
| `ORG_MCP_RUN_ID` | test 必填且以 `test-` 或 `test_` 开头；production 可省略 |
| `ORG_MCP_CASE_ID` | 可选用例标识；每个 CI 用例应独立实例化身份 |
| `ORG_MCP_CONFIRMATION_TIMEOUT` | 有限正数秒，默认 `60`，限制人工确认等待 |

令牌由密码管理器分别生成并写入受限环境配置，禁止写入镜像、命令行、URL 或报告。入站与后台 token 必须不同、非空且满足 ASCII 无空白/控制字符约束。默认 profile 不增加强制令牌插值；启用侧车后缺少或错误配置会安全失败关闭。可选 run/case 的空环境值按省略处理，不存在静态 approved 配置或同义变量别名。`.env` 由 Compose 解析后逐项注入侧车；MCP Python 模块自身不读取 `.env`。

受信客户端必须位于可达能力网络的受控部署环境，连接 `http://mcp:8001/mcp`（自定义端口时相应替换），并使用独立 MCP Bearer token。SDK 的 DNS rebinding 防护始终启用：仅允许当前端口的 `127.0.0.1`、`localhost`、`[::1]`、`mcp` 和显式的非通配监听名；Origin 若存在，须为这些地址的 `http://` origin。通配监听地址不会被加入允许 Host。新域名或 HTTPS 代理应另行审查可信入口配置，不应关闭鉴权或全部 Host 检查。MCP 没有公开端口，后台 `/internal` 仍须由外部代理拒绝。

健康检查模块 `python -m app.mcp.health` 读取相同配置，通过官方 MCP SDK 对真实 `/mcp` 进行初始化和 `list_tools`，要求完整 15 工具目录；不调用业务工具、数据库或飞书。单次总异步截止 4 秒，HTTP 超时 2 秒，Compose 探针上限 8 秒。绑定 `0.0.0.0`/`::` 时分别以 IPv4/IPv6 回环探测。成功退出 0 并输出 `MCP_READY`，任何连接、认证、配置或目录错误退出 1，只输出固定 `MCP_NOT_READY`。此探针只证明适配器协议就绪，后台就绪由既有 app health 依赖负责；没有额外 `/health` 路由，也不声称后台业务事实已验证。

本机调试时，在隔离 shell 注入同名合成配置，设置 `ORG_MCP_HOST=127.0.0.1` 和本机端口、`ORG_MCP_CAPABILITY_BASE_URL` 指向隔离内部服务，再从 backend 目录执行：

```powershell
.venv/Scripts/python.exe -m app.mcp --transport streamable-http
.venv/Scripts/python.exe -m app.mcp.health
```

CLI 的 `--host` / `--port` 优先于环境配置，参数中不传令牌。ASGI 工厂仍为 `app.mcp.config:create_app`；使用 uvicorn factory 时，uvicorn 的 `--host` / `--port` 必须由部署方显式设为与 `ORG_MCP_HOST` / `ORG_MCP_PORT` 相同，工厂配置不控制 uvicorn 自身监听。推荐使用上述 MCP CLI，确保监听与 Host 防护使用同一配置。

生产 human_agent 的 L2 写入须经支持官方 MCP elicitation 的受信客户端展示实际参数并取得人工确认；decline、cancel、不支持或超时均拒绝。test 环境的合法 ci_agent 可由策略自动确认，仅连接隔离 `_test` 数据库的内部服务，不能把该身份用于 production。`approved`、主体身份及内部认证头不接受模型输入或客户端任意同名头赋权。写入超时后先调用 `get_operation`，不自动重试写操作。

本任务已通过真实本机隐藏子进程的 MCP 启动、认证、两种协议模式发现、`mcp` Host/Origin 兼容及探针成功/失败检查；后台地址使用不可用回环端口且未调用业务工具。Compose 以固定版本 PyYAML `safe_load` 检查结构。Docker daemon 不可用，本轮未实际构建或运行容器，也未验证容器 DNS/网络隔离或真实数据库/飞书链路，不能将本机结果视为容器部署验收。
