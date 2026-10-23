# 数据库整改执行与验证包

适用版本：MySQL 8.4 / InnoDB；起始版本 `0005_sync_job_ledger` 或 `0006_column_comments`，目标 `0008_session_digest`。本包提供代码与操作步骤，不代表已获得业务库执行授权，也不代表已部署。开发、测试、生产必须分别记录实际版本和结构。

## 当前交付状态

- 代码实现和离线 SQL 校验已完成；普通文本统一 `utf8mb4_general_ci`，稳定 ID/业务键保留 `utf8mb4_bin`。
- 历史迁移定义冻结在 `backend/migrations/schema_20261022.json`；在线先核对类型、空值、默认值、自增、注释、字符集与列集合，再从 `SHOW CREATE TABLE` 保留完整列定义。生成列、额外属性或未预期人工变更会被阻断，需人工审查，不能覆盖。
- `0006` 在线/离线均生成实际注释 DDL，回退恢复 `0005` 注释（包括 `0004/0005` 原有说明）。离线定义采用历史普通文本 `utf8mb4_0900_ai_ci`；只有与该冻结基线匹配的目标才能直接执行离线包。其他已确认排序规则的已有库使用在线迁移保留元数据。
- `0007` 先检查目标排序规则下的所有现有唯一键、既有外键兼容性和孤儿数据，再修改数据库/表默认值与普通文本列。跨库外键阻断。不会删除索引、外键或修改初始化状态。
- `0008` 撤销全部既有管理员会话，将原令牌转换成摘要并替换内部 ID；保留行数、摘要唯一性和撤销状态。不可还原旧令牌。应用全部管理员需重新登录。
- `/health/ready` 只读校验版本、所有业务表/字段和关键单例；`pending` 初始化状态允许管理端进入，不代表组织数据已初始化。
- 本机 Docker 引擎当前不可连接；真实 MySQL 升级/回退/中断/恢复及 HTTPS 登录尚未验证。历史审计中的数据库版本和会话数量不是当前在线证据。

2026-10-22 本地验证记录：后端全量 `pytest -q -p no:cacheprovider` 为 **112 passed / 13 skipped**；13 项跳过均需要独立 MySQL（既有 6 项、新增迁移 7 项）。`compileall` 和 `git diff --check` 通过；离线 head、0006 升级、0006 回退分别生成 363、140、140 条语句。标准轴与规格轴审查发现的问题已修复并复核。剩余警告来自 Starlette/AnyIO 与 Alembic 配置弃用提示，不影响本轮测试退出码。未执行提交后的部署，也未变更产品发布版本。

## 既有项目规则例外

保持已存在的字符串/复合主键、BigInteger 日志主键、`created_at/updated_at` 应用维护模式、外键、`uq_`/`ix_` 索引命名和 JSON/TEXT 类型。此整改只调整已确认的注释、默认值表达、排序规则、会话摘要与就绪检查，不按通用 Skill 默认值重建业务模型。`alembic_version` 是 Alembic 管理的兼容性版本表，历史迁移不改写该外部管理对象的列注释。

## 只读检查入口

在 `backend` 目录运行；数据库 URL 通过受控环境变量 `ORG_DATABASE_URL` 注入，不把真实 URL 写入命令历史或报告。

```powershell
# 迁移前受限结构快照，不包含业务行或令牌；保存至 backups（已忽略）
New-Item -ItemType Directory -Force ../backups | Out-Null
./.venv/Scripts/python.exe -m app.persistence.schema_check --snapshot-only > ../backups/schema-before.json
if ($LASTEXITCODE -ne 0) { throw '结构快照失败' }

# 旧版本预检：元数据、唯一键、外键、孤儿和固定比较语义样本
./.venv/Scripts/python.exe -m app.persistence.schema_check --preflight
if ($LASTEXITCODE -ne 0) { throw '迁移预检失败，禁止执行 DDL' }

# 只有准备对已有库执行离线 SQL 时追加此检查，通用预检不能代替它
./.venv/Scripts/python.exe -m app.persistence.schema_check --preflight --offline-baseline
if ($LASTEXITCODE -ne 0) { throw '不匹配离线冻结基线，改用在线迁移' }

# 完成迁移后：对比当前 ORM 和真实结构，任何差异返回非零
./.venv/Scripts/python.exe -m app.persistence.schema_check
if ($LASTEXITCODE -ne 0) { throw '结构验收失败，保持应用停写' }
```

检查器输出版本、数据库/表/列字符集和排序规则、连接时区/隔离级别、注释、默认值、生成表达式、自增、主键、唯一键、普通索引与外键。退出码：0=通过/快照成功，1=结构不匹配，2=连接或预检失败。`--snapshot-only` 不代表结构合格。错误报告不输出连接异常原文或凭据。

## 独立 MySQL 演练

`compose.mysql-test.yaml` 使用独立 Compose 项目、13308 端口、公开测试密码和 tmpfs；不挂载业务数据库卷。以下仅针对该可丢弃实例。迁移测试另用随机 `tmp_org_*_test` 库，退出时只删除本次创建的库。

```powershell
../scripts/check-environment.ps1 -DatabaseIntegration
if ($LASTEXITCODE -ne 0) { throw '数据库集成环境未就绪' }
docker compose -f compose.mysql-test.yaml up -d --wait
if ($LASTEXITCODE -ne 0) { throw '隔离 MySQL 未就绪' }
$env:ORG_MIGRATION_TEST_DATABASE_URL = 'mysql+pymysql://root:isolated-test-only@127.0.0.1:13308/organization_remediation_test'
Push-Location backend
try {
    ./.venv/Scripts/python.exe -m pytest tests/integration/test_mysql_remediation_migrations.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw '迁移演练失败' }
    # 给既有事务/恢复用例准备专用库；只写上面创建的测试实例
    $env:ORG_DATABASE_URL = $env:ORG_MIGRATION_TEST_DATABASE_URL
    ./.venv/Scripts/python.exe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw '测试库迁移失败' }
    $env:ORG_TEST_DATABASE_URL = $env:ORG_MIGRATION_TEST_DATABASE_URL
    ./.venv/Scripts/python.exe -m pytest tests/integration -q -p no:cacheprovider --require-mysql
    if ($LASTEXITCODE -ne 0) { throw 'MySQL 集成验收失败' }
} finally {
    Pop-Location
    Remove-Item Env:ORG_DATABASE_URL, Env:ORG_TEST_DATABASE_URL, Env:ORG_MIGRATION_TEST_DATABASE_URL -ErrorAction SilentlyContinue
    docker compose -f compose.mysql-test.yaml down
}
```

在专用终端执行，避免覆盖已有业务连接变量。测试包含 `0005→0006→0005` 完整结构快照比对、新库离线 SQL 执行、head 与 ORM 对齐、连接重建、唯一键冲突先行阻断，以及摘要迁移在加列/收紧约束/建唯一索引后中断重试。

备份恢复演练还需在该隔离实例中按 `deploy/README.md` 的一致性备份与恢复顺序执行：恢复后保持应用停写，先升级到 head，再执行恢复工具撤销 API 凭据、重置数据世代，核实会话全部失效。不得把事务恢复单元测试等同于 mysqldump/导入演练。

## 目标库执行顺序（需另行授权）

1. 分环境核实目标实例、库名、MySQL 版本、迁移版本、表行数、外部引用及预计 DDL 锁等待。完成独立演练并审阅结果。
2. 停止应用、worker、事件监听及其他写入方。记录管理员会话总数、撤销数和过期数；不把原主键（旧令牌）导出到普通日志或结构报告。
3. 按部署说明完成一致性备份并验证可恢复性；旧备份含可直接认证的会话值，必须受限、加密保管。保存受限结构快照。备份失败立即停止。
4. 运行 `--preflight`。审阅固定样本的大小写/重音/尾空格比较结果，并按实际业务样本核对查询及排序。冲突需经业务确认处理后重新预检。
5. 使用当前构建的 `python -m alembic upgrade head` 在线执行。离线 `upgrade head --sql` 仅是可审查交付物，不能跳过目标库预检；离线文件不适用于中断后直接重放。
6. 运行无参数 `schema_check`、比对迁移前后业务表行数、会话总数和撤销数；核对所有旧会话 ID 已替换，禁止打印 ID/令牌/摘要清单。
7. 启动新代码，分别核对 HTTP/worker/监听连接会话参数以及重连后的配置。调用 `/health/live` 和 `/health/ready`；旧代码不能继续连接已完成摘要迁移的库。
8. 在正式 HTTPS 入口验证重新登录、刷新、旧 Cookie 拒绝、注销、CSRF 拒绝、移出白名单和停用员工立即拒绝。初始化与飞书覆盖状态仍单独验收。

## 中断与失败恢复

- MySQL DDL 隐式提交，不能把 Alembic 事务当作全量回滚保障。发生错误保持全部写入进程停止，保存受限结构快照和 revision。
- `0006` 使用在线检查并保留完整列定义，可重复应用；在线回退仅用于与冻结基线一致的 `0006→0005`。意外差异会在 DDL 前阻断。
- `0007` 元数据调整可在线重试；不自动推断原排序规则回退。需要撤回时，根据该目标库迁移前快照审核恢复 SQL；不直接执行到 `0005` 的降级。
- `0008` 可从已加摘要列、已完成数据转换、已收紧非空或已建立唯一索引的中断状态正向重试。重试检查既有列/索引形状和外键，再转换未完成记录。所有旧会话保持撤销。
- 必须恢复旧备份时，先隔离登录和所有业务写入，恢复后重新完成 `0008` 以及凭据撤销，再上线兼容版本。禁止重新开放旧会话，禁止把摘要还原为令牌。
- 数据数量不一致、摘要重复、外键/类型漂移、结构检查失败或 HTTPS 登录验证失败时，不解除维护状态。
