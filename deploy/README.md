# 部署说明

## 标准部署入口

开发完成默认部署**本地 Docker**；线上测试与正式环境仅在用户当次明确要求时部署。环境台账、固定命令、制品、验证、回退及授权边界统一见 [环境与标准发布流程](ENVIRONMENTS.md)，配置源为 `environments.json`，脚本入口为 `release.py`。

普通更新使用 `backend/.venv/Scripts/python.exe deploy/release.py deploy`，默认仅更新本地 app/MCP。数据库版本不匹配时必须停止，另行执行已授权的迁移流程。以下历史首次搭建和迁移命令不替代标准发布入口；使用新脚本后启动必须带其镜像覆盖配置，不能直接 `docker compose up --build` 覆盖已验收版本。

## 产品版本与构建

产品版本从根目录 `version.json` 读取，规范见 [版本规范](../docs/versioning.md)。当前重设的开发初始基线为 0.1.0，尚未正式上线。普通开发构建不显示发布日期；旧容器不会因文件修改自动更新版本，需另行构建并部署镜像后核对系统信息页。

Docker 构建时生成同一份 `build-info.json`，分别注入前端和 Python 包；通过 `/admin/api/system/version`（管理员认证）读取服务端版本，不查询业务数据库。开发镜像可用 `--build-arg ORG_COMMIT_SHA=<完整SHA> --build-arg ORG_SOURCE_DIRTY=true` 标识未提交代码。发行构建由干净 tag 提交进行，同时传入 `ORG_RELEASE_TAG`、`ORG_COMMIT_SHA` 和 `ORG_SOURCE_DIRTY=false`；应用、迁移和 MCP 继续复用同一镜像。不得将未知提交或脏代码构建标记为已发行。

2026-10-24 的 MCP 分支整合、`0008→0009` 升级及本机容器验收见 [MCP 整合验收记录](../docs/mcp-integration-acceptance-2026-10-24.md)。app、migrate、mcp 复用同一构建镜像，避免服务与迁移代码不一致。

数据库 `0006—0008` 整改的预检、隔离演练、执行和恢复步骤见 [数据库整改执行包](../docs/database-remediation-runbook-2026-10-22.md)。生成迁移不代表已执行；摘要迁移后所有管理员必须重新登录。

## 准备配置

在项目根目录将 `.env.example` 复制为 `.env`，填写随机数据库密码、至少 32 字符的会话密钥、飞书企业自建应用信息和同应用初始管理员 `open_id`。数据库 URL 的密码与 `MYSQL_PASSWORD` 一致。部署地址需要 HTTPS，登录回调固定为 `/admin/auth/callback`。

`.env` 不进入镜像或版本控制。MySQL 容器不映射公网端口，应用默认仅监听宿主机 `127.0.0.1:8000`，由部署方的 HTTPS 入口转发。

```powershell
Copy-Item -LiteralPath .env.example -Destination .env
# 用本机编辑器填好 .env 后执行：
docker compose up -d --build
docker compose ps
```

Compose 先等待 MySQL 就绪，再运行 Alembic 迁移，迁移成功后启动应用。应用进程监督器负责 HTTP、同步 worker 与飞书长连接三个独立进程；任一必要进程意外退出时终止其余进程，由容器重启恢复。长连接回调仅快速持久入箱，远程回查由 worker 执行；已初始化时启动和断线恢复后安排全量核对，未初始化时保持事件监听但不提交普通核对任务。

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

该命令以单事务重置世代、隔离旧事件与未完成任务、撤销 OAuth state/会话/API 凭据，并写审计。此时门店资料与来源事实暂时保留；初始化变为 pending，向导进入 cleanup_required。管理员随后在向导中发起清理并重新初始化，清理包含门店编码和备注；初始化成功前业务读取被门禁阻止。责任人参数必须填写实际标识。

如果备份中已无可用管理员，可在该命令中明确追加 `--admin-open-id ou_实际标识`，把经线下核验的同应用人员加入白名单并写审计。环境变量中的初始白名单只在首次初始化生效，重启不会自动恢复被删除的管理员。

2026-10-24 已在独立 MySQL 8.4.11 测试实例完成合成数据的实际 mysqldump 导出、导入及恢复后世代/凭据重置，证据见[数据库整改执行包](../docs/database-remediation-runbook-2026-10-22.md)。业务环境的备份恢复、飞书全量核对和正式登录仍需分别验收。

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
 docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -e "DROP DATABASE IF EXISTS organization; CREATE DATABASE organization CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"'

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

重启后由管理员在全屏向导中重新初始化，明确清除旧业务资料，再完成预检、覆盖验收及全量同步。确认新 `dataset_epoch`、初始化完成和覆盖状态；旧门店编码／备注已清除，按需要重新维护，再通知下游重新全量拉取。

## 数据库集成测试

Agent Evaluation 使用通用 Python 模块入口，默认串行。先准备独占、可清空的 MySQL 8.4 `_test` 库，字符集与排序规则为 `utf8mb4` / `utf8mb4_general_ci`；按[测试迁移与评测命令](../docs/运行与验收.md#agent-evaluation-测试迁移与命令)核实实际目标并迁移。不要把已有生产环境的 `ORG_DATABASE_URL` 带入迁移进程。

从仓库根目录执行（凭据通过受控环境注入 `ORG_TEST_DATABASE_URL`，不要写入命令、报告或 Git）：

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation deploy/tests/test_evaluation_runtime.py -q
backend/.venv/Scripts/python.exe -m app.evaluation.cli --suite smoke --output .superpowers/evaluation-reports
```

CLI 的 `--case ORG_AGENT_VERSION_CONFLICT` 可筛选单例；退出码 `0` 为全部硬门槛通过、`1` 为硬断言失败、`2` 为配置/迁移/环境安全失败。没有实际 `_test` MySQL 不会降级为 SQLite 或模拟成功。报告为脱敏 JSON/中文 Markdown，软评分不改变退出码。脚本 Worker 与 Fake Feishu 用于普通 CI；真实模型、企业飞书和 Docker 运行分别验收。

默认输出五维规则软分及 `llm_judge.status=disabled`。可选模型诊断必须由可信调用方显式注入 model、provider 与 `redacted_test_only` 策略，当前只发送允许的工具名、布尔值与行数，自由文本整体遮盖；模型异常仅记录安全失败状态。配置和元数据位置见[软诊断口径](../docs/运行与验收.md#agent-evaluation-软诊断)，普通 CLI 不隐式启用外部模型。

`compose.mysql-test.yaml` 是可丢弃的独立本机测试环境，使用公开的测试密码和 tmpfs，不用于正式部署。它显式设置数据库 `utf8mb4` / `utf8mb4_general_ci`，仅绑定 `127.0.0.1:13306`，库名必须以 `_test` 结尾。

迁移前检查、凭据文件格式、隔离环境的执行命令及 2026-10-15 便携 MySQL 8.4.11 的真实结果见[能力与观察层验收](../docs/运行与验收.md#能力与观察层验收2026-10-15)。上述 18 项是 2026-10-15 便携 MySQL 的历史结果；当前容器验收以 2026-10-24 整合记录为准，企业飞书与真实模型仍另行验收。

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

2026-10-16 的验收使用本机隐藏子进程；当时 Docker 不可用。2026-10-24 已进行真实独立 Docker/MySQL/MCP 链路验收，最新范围与结果见上述整合记录。历史记录不代表当前环境。

## 本机 MCP 客户端接入（stdio）

Docker 的 `internal` 能力网络实测不发布宿主机端口。保留该隔离配置，本机受信客户端通过 Docker 执行官方 stdio 入口；服务不需要开放公网或回环 TCP 端口。

客户端进程使用 `powershell.exe`，参数为 `-NoProfile -File` 和仓库中 `deploy/mcp-stdio.ps1` 的绝对路径。脚本以固定仓库路径执行 `docker compose --profile agent exec -T mcp python -m app.mcp --transport stdio`。需要 app/mcp 容器已运行及当前用户有 Docker 权限。此操作不会把令牌放在参数或客户端配置里，业务主体固定来自 MCP 容器可信环境；持有 Docker 权限等同受信本机运维权限。

stdio 与 HTTP 使用同一工具、身份、版本、幂等和人工确认策略。客户端必须支持 MCP elicitation 才能完成生产写入；不支持、拒绝、取消或超时均不提交。接入示例（替换为实际仓库绝对路径）：

```json
{
  "mcpServers": {
    "organization-directory": {
      "command": "powershell.exe",
      "args": ["-NoProfile", "-File", "D:\\WorkBench\\AI Projects\\OrganizationalStructure\\deploy\\mcp-stdio.ps1"]
    }
  }
}
```

部署人员可执行 `docker compose --profile agent exec -T mcp python -m deploy.mcp_acceptance`，通过官方 HTTP 客户端验证完整目录、实际后台只读调用和人工拒绝边界。该命令会发起并明确拒绝一次合成同步申请，不会批准修改；输出只包含固定检查结果。健康探针只发现工具，不能代替此业务链路验收。

### 腾讯云受信 SSH 客户端

`deploy/mcp-stdio-ssh.ps1` 通过本机 SSH 别名 `tencent_test_col` 连接 `/srv/organization-directory` 的 `compose.json`，在远端 MCP 容器中启动 stdio；它与上面的本机入口是两个独立环境。SSH 要求现有可信主机记录、非交互密钥认证及远端受控的 Docker 执行权限，不自动接受陌生主机密钥、不输出服务令牌，也不公开 MCP 端口。

```powershell
codex mcp add organization-directory-cloud -- powershell.exe -NoProfile -File "D:\WorkBench\AI Projects\OrganizationalStructure\deploy\mcp-stdio-ssh.ps1"
```

该注册只添加云端入口，不替换本机 `organization-directory`。新增后需在客户端重新加载并确认工具目录；注册成功不等于当前对话已经加载工具，也不等于已经批准业务写入。云端部署与验收状态见 [接入与业务验收记录](../docs/mcp-client-and-live-acceptance-2026-10-24.md)。

## Pro / Umi 管理端构建

前端采用 Umi Max 4.7.23、Utoopack 和 ProComponents 3.1.14-2（预发布），沿用 Node 24 多阶段构建及 Python 3.13 单应用镜像。Docker 在复制前端、版本脚本和版本声明后执行严格 `npm ci`，postinstall 生成 Umi 类型；不复制宿主机 `.umi` 和缓存。`ORG_BUILD_INFO_FILE` 继续把同一份元信息交给前后端。

静态入口支持根级与子目录 JS/CSS/chunk、字体、图片和 `build-info.json`，检查解析后的目录边界；入口和元信息使用 `no-cache`，缺失资源及保留 API/认证路径返回 404，业务导航回退到 index.html。回滚必须使用配套的完整镜像，同时回退入口、chunk 和元信息；无需数据库迁移。

验证状态与 Docker Hub 网络限制见[迁移验收记录](../docs/architecture/ant-design-pro-migration-acceptance-2026-10-25.md)。

## 初始化向导迁移（0010）

本节为执行手册，不代表已部署或已获得目标业务库执行授权。适用于 MySQL 8.4；迁移为 `backend/migrations/versions/0010_initialization_wizard.py`，沿用现有表、字段、中文注释、字符集、索引与约束。已确认流程与清理边界见[初始化实施记录](../docs/architecture/initialization-wizard-clarification-2026-10-26.md)。

### 执行前检查

1. 明确环境、Compose 项目、目标库和匹配镜像；停止 HTTP、worker、飞书监听和其他写入方，保留迁移前备份并验证其可恢复。连接凭据使用受限配置，不写入命令行或日志。
2. 使用应用连接工厂只读核验实际 MySQL 版本、会话 `utf8mb4` / `utf8mb4_general_ci` 及数据库规范；按 `schema_snapshot` 保存结构证据，包含原有 `utf8mb4_bin` 稳定 ID 列。不要用运维客户端的会话设置替代应用会话证据。
3. 对已有实例记录下列查询结果。升级前版本应为 `0009_operation_receipt`；更早版本先审查其全部中间迁移。已经是 `0010_initialization_wizard` 时不得手工重跑本迁移 SQL。

```sql
SELECT VERSION(), DATABASE(), @@character_set_connection, @@collation_connection;
SELECT version_num FROM alembic_version;
SELECT id, dataset_epoch, data_version, initialization_status, coverage_status FROM dataset_state WHERE id = 1;
SELECT (SELECT COUNT(*) FROM department) AS departments,
       (SELECT COUNT(*) FROM employee) AS employees;
SELECT status, COUNT(*) AS jobs FROM sync_job GROUP BY status;
SELECT status, COUNT(*) AS events FROM event_inbox GROUP BY status;
SELECT id, generation, owner, expires_at FROM worker_lease WHERE id = 1;
SELECT `key`, JSON_UNQUOTE(JSON_EXTRACT(value, '$.phase')) AS phase
FROM system_setting WHERE `key` = 'initialization_flow';
```

### 执行与验证

在目标执行获准后，沿用 Compose 的 `migrate` 服务执行 Alembic 升级至 head，成功后再启动匹配的新应用。不要让旧应用与新版本同时写入。迁移将旧完成标记改为 pending、覆盖改为 unknown，隔离旧排队／运行任务和排队事件，释放旧 worker 租约，并写入 `migration:0010` 审计；迁移本身不清理部门、人员或门店资料。

执行后复核上述查询：版本为 `0010_initialization_wizard`，旧实例流程为 `cleanup_required`（全新空实例为 `pending`），旧活动任务已终结，旧队列事件已隔离，旧租约已释放；业务数量与迁移前一致。对比迁移前后结构快照，除版本与状态数据外，不应出现结构变化。

启动后检查 HTTP、worker 与飞书监听均持续运行；非管理员仍不可登录，管理员只能进入向导。旧实例点击“重新初始化”才清理业务资料及门店编码／备注；前四步通过后点击“立即同步”。最终提交成功后核验 `initialization_status=complete`、流程 complete、任务 succeeded 和覆盖 complete。再次重启或执行正常 `upgrade head` 后完成状态保持，不能重复清理。真实企业权限、字段及全员／无部门名单须按向导提供证据验收。

### 失败恢复

迁移失败时保持停写，保留错误与迁移版本证据；MySQL 迁移可能部分提交，不得假定自动回滚全部语句。`0010` 的 downgrade 明确拒绝自动恢复旧完成标记。恢复应使用迁移前备份及对应旧镜像，并按恢复规范撤销会话和凭据、隔离旧任务；不得仅修改 Alembic 版本或完成字段。

已经在新向导中清理或写入新数据后，回退备份会丢失备份之后的数据，须先保存现状并确认恢复范围。继续使用新版本恢复备份时，先迁移至当前 head，再执行本手册的恢复状态重置，随后由管理员重新完成向导。初始化同步失败按页面“重新开始”处理，不以数据库降级替代流程重试。
