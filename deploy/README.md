# 部署说明

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

重启后由管理员创建全量同步任务，确认新 `dataset_epoch`、初始化完成、覆盖验收状态和门店资料，再通知下游重新全量拉取。

## 数据库集成测试

`compose.mysql-test.yaml` 是可丢弃的独立本机测试环境，使用公开的测试密码和 tmpfs，不用于正式部署。用户提供数据库环境后执行真实 MySQL 事务、并发、迁移与恢复验证。
# 覆盖权限重新验收

通讯录 scope 变更后，覆盖状态降为 unknown。具备部署主机及数据库配置权限的运维人员完成真实企业验收（已发布应用的全员权限、无部门员工覆盖）后，在 `backend` 目录执行：

```powershell
./.venv/Scripts/python.exe -m app.sync.coverage --reference "企业验收记录-2026-09-15-02" --actor "operator:运维人员" --all-members-verified --departmentless-verified
```

Linux 使用部署环境的 `python -m app.sync.coverage`，参数相同。沿用 `ORG_DATABASE_URL/ORG_SESSION_SECRET/ORG_FEISHU_APP_ID/ORG_FEISHU_TENANT_KEY`；执行前先迁移到最新版本（含 `0003_pending_fact`）。reference 应为验收编号/摘要，不得填写 token/secret。

CLI 将新依据、标记清除、审计与新全量核对任务同事务提交，返回 job_id。该命令不会把覆盖直接改为 complete；worker 后续采集成功才能恢复，旧在途采集不能恢复。无需修改或手工删除数据库行。此文档提供执行方式，本轮没有对真实环境执行。
