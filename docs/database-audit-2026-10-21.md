# 数据库检查记录（2026-10-21）

本次已只读连接本机正在运行的 `organization` 数据库，并核对 ORM、Alembic 迁移、应用连接、Compose 和恢复说明。数据库可访问，迁移已到仓库最新版本；规范一致性、会话凭据存储和迁移回退仍有需要修复的问题。

检查基线为 `database-conventions` 技能、仓库 `AGENTS.md` 及当前实现。项目已明确使用 MySQL 8.4、InnoDB、utf8mb4，Compose 的排序规则为 `utf8mb4_0900_as_cs`；本报告不把技能默认的 `utf8mb4_general_ci` 当成项目应自动切换的目标。

## 检查范围与证据边界

| 项目 | 本次核验结果 |
| --- | --- |
| 工作区 | `D:\WorkBench\AI Projects\OrganizationalStructure` |
| 分支及提交 | `main`，`a3c3836`；工作区已有其他未提交内容，本次检查未修改这些内容 |
| 数据快照时间 | 2026-10-21 17:54:24（北京时间）；后续会话核验发生在同次检查期间 |
| 本机应用容器 | `organization-directory-app-1`，运行且健康 |
| 本机数据库容器 | `organization-directory-mysql-1`，运行且健康；Compose 标签确认属于当前工作区 |
| 数据库入口 | 容器内 `mysql:3306/organization`；宿主机映射 `127.0.0.1:13307` |
| 数据库实际版本 | MySQL **8.4.11** |
| 本地驱动与迁移依赖 | SQLAlchemy 2.0.43、PyMySQL 1.1.2、Alembic 1.16.5 |
| 独立测试环境 | 有 Compose 配置，但本次未发现对应运行容器，未配置 `ORG_TEST_DATABASE_URL`；未执行写入型集成测试 |
| 独立生产环境 | 当前上下文没有指定另一套生产连接；本次结论不外推到远端环境 |

数据库采集使用只读事务，内容限于元数据、聚合计数、状态字段和 EXPLAIN；未读取或输出员工明细、密码、令牌、会话值。未执行迁移、回退、数据清理或配置变更。回退验证仅在内存中捕获生成的 SQL，没有向数据库发送 DDL。

## 实际数据库状态

| 检查项 | 结果 |
| --- | --- |
| Alembic 实际版本 / 仓库 head | 均为 `0006_column_comments`，单一迁移链，共 6 个版本 |
| 表与字段 | 21 张业务表、137 个业务字段；另有框架表 `alembic_version` |
| 存储引擎与字符集 | 所有表为 InnoDB；字符串字段为 utf8mb4 |
| 数据库 / 服务端默认排序规则 | `utf8mb4_0900_as_cs` |
| 业务表默认排序规则 | **21 张均为 `utf8mb4_0900_ai_ci`**；框架表为 `utf8mb4_0900_as_cs` |
| 字符列排序规则 | 43 个字段为 `utf8mb4_bin`，44 个为 `utf8mb4_0900_ai_ci` |
| 应用连接会话 | 实测字符集 utf8mb4，排序规则 **`utf8mb4_0900_ai_ci`** |
| 连接时区与隔离级别 | `time_zone=SYSTEM`，当前系统时区 UTC；`REPEATABLE-READ` |
| SQL 模式 | 包含 `STRICT_TRANS_TABLES`、`ONLY_FULL_GROUP_BY`、`NO_ZERO_DATE`、`NO_ZERO_IN_DATE` |
| 外键 | 10 组，类型、字符集、排序规则全部兼容；`foreign_key_checks=1` |
| 孤儿记录 | 对全部 10 组外键关联执行只读检查，结果为 0；相关业务表目前为空 |
| 索引 | 全库 39 个物理索引，包含框架表主键；模型声明的索引和唯一约束均存在 |
| 中文字段注释 | 实际库 137/137 个业务字段均有中文注释 |
| 中文表注释 | 21/21 张业务表均缺失；框架表也无表注释 |
| 其他数据库对象 | 当前账号可见的视图、触发器、存储例程、Event 均为 0 |
| 数据与索引分配量 | information_schema 汇总约 1.44 MiB；不是备份大小，也不是精确业务数据量 |

应用容器内另外通过项目 `create_mysql_engine` 新建连接，得到与宿主机探测相同的字符集、排序规则、UTC 系统时区及隔离级别。此结果验证了应用连接工厂的实际行为，未假定所有已有连接池会话相同。

业务状态快照：

| 状态 | 结果 |
| --- | --- |
| 初始化 | `pending` |
| 覆盖状态 | `unknown` |
| 数据版本 | `data_version=0` |
| 最近全量同步 | `NULL` |
| 飞书连接状态 | `degraded`，覆盖状态 `unknown` |
| 同步任务 | 1 个 `initialize/queued`；1 个 `reconcile/queued/waiting_initialization` |

这些状态说明当前尚未形成可使用的组织数据集；排队或飞书连接降级的原因不由数据库结构检查直接确定。本次没有发起同步。

| 业务表 | 字段数 | 精确行数 |
| --- | ---: | ---: |
| `department` | 9 | 0 |
| `employee` | 18 | 0 |
| `employee_department` | 4 | 0 |
| `employee_store` | 4 | 0 |
| `store_profile` | 4 | 0 |
| `store_code_reservation` | 3 | 0 |
| `sync_job` | 23 | 2 |
| `sync_job_detail` | 12 | 0 |
| `sync_staging` | 4 | 0 |
| `pending_fact` | 5 | 0 |
| `event_inbox` | 7 | 0 |
| `change_log` | 9 | 0 |
| `dataset_state` | 6 | 1 |
| `system_setting` | 2 | 4 |
| `worker_lease` | 4 | 1 |
| `feishu_connection` | 6 | 1 |
| `admin_allowlist` | 2 | 1 |
| `admin_session` | 5 | 5 |
| `api_client` | 5 | 0 |
| `login_identity` | 3 | 1 |
| `oauth_state` | 2 | 1 |

以上计数是检查时的快照；应用持续运行，登录和任务状态可能继续变化。会话行数不等于当前有效登录人数。

## 需要处理的问题

### 1. 高优先级：管理员会话凭据以可直接使用的形式入库

已核对完整代码路径：

- `backend/app/feishu/oauth.py:50` 生成随机值并直接保存到 `admin_session.id`。
- `backend/app/main.py:109` 将同一个 `session.id` 写入 `org_session` Cookie。
- `backend/app/dependencies.py:54` 把 Cookie 原值传给认证仓储。
- `backend/app/persistence/repositories.py:36` 直接按 `AdminSession.id == session_id` 查询，结合有效期、撤销和白名单判断身份。

因此，该列实际保存的是会话持有者凭据，而不仅是普通业务标识。数据库或备份读取权限泄露时，仍有效的会话值可被用于通过会话认证。这违反技能关于不存储明文令牌及可直接使用凭据的要求。此结论来自代码路径；本次没有提取或重放任何真实会话。

建议后续改为数据库仅保存会话凭据摘要，并设计现有会话的兼容或失效策略。API 密钥使用 scrypt 摘要、CSRF 使用 HMAC、OAuth state 使用 SHA-256，这些路径已具备摘要存储。

### 2. 高优先级：0006 回退会改变字段定义，并可能部分失败

位置：`backend/migrations/versions/0006_column_comments.py:78`。

`downgrade()` 的注释写着“不触碰字段定义和数据”，实际却重新执行 `MODIFY COLUMN`，仅保留字段类型和 NULL 属性，遗漏字符集/排序规则、默认值、AUTO_INCREMENT 等属性。

以本次实际元数据进行内存模拟，捕获了 137 条回退 DDL，其中：

```sql
-- 仅为问题证据，本次没有执行这些语句。
ALTER TABLE `department` MODIFY COLUMN `id` varchar(191) NOT NULL COMMENT '';
ALTER TABLE `feishu_connection` MODIFY COLUMN `custom_attrs` json NOT NULL COMMENT '';
ALTER TABLE `sync_job` MODIFY COLUMN `execution_count` int NOT NULL COMMENT '';
ALTER TABLE `change_log` MODIFY COLUMN `id` bigint NOT NULL COMMENT '';
```

这些语句分别没有保留来源 ID 的 `utf8mb4_bin`、JSON 默认值、计数默认值和自增属性。根据 MySQL DDL 行为，回退可能改变字段语义，或在被外键引用的字段处失败；此前已经完成的 DDL 不能依赖事务整体回滚。没有在真实库执行破坏性回退，因此本报告不声称已复现具体 MySQL 错误码。

此外，统一清空注释不能恢复 0004/0005 已有的原始注释。后续修复应保留完整元数据，并提供逐步检查与失败恢复说明。

### 3. 中优先级：数据库、表、连接和恢复入口排序规则不统一

已确认的实际差异是：库及服务端为 `utf8mb4_0900_as_cs`，所有业务表默认值及应用连接为 `utf8mb4_0900_ai_ci`，来源标识等字段显式使用 `utf8mb4_bin`。

相关代码仅声明表的 `mysql_charset`，未声明 `mysql_collate`；连接工厂也没有固定会话排序规则：

- `backend/app/persistence/models.py:7`。
- 0001、0002、0003、0005 的建表参数。
- `backend/app/persistence/database.py:11`。

另一个入口 `deploy/README.md:81` 的恢复重建库示例使用 `utf8mb4_bin`，与 Compose 的 `utf8mb4_0900_as_cs` 不同。

`ai_ci` 与 `as_cs` 在重音及大小写比较上不同，不能作为同一种规则描述。当前 10 组外键字段均为匹配的 `utf8mb4_bin`，本次未发现外键兼容性故障；连接排序规则不同也不等于所有列比较都会立即失效。

后续应明确普通文本、稳定标识、库/表默认值和连接各自的规则，再统一建表、迁移、ORM、连接和恢复文档。任何实际排序规则转换都需要另行核对唯一键冲突、关联数据和比较语义，本次未转换。

### 4. 中优先级：ORM、迁移与实际库的注释及默认值存在差异

实际数据库经过 0006 后，137 个业务字段都有中文注释；ORM 中仍有 **106 个字段缺少注释**，另有 **13 个字段注释文本与实际库不同**。所有业务表在 ORM、迁移和实际库中均没有表注释。

使用只读 Alembic 元数据比较，得到：

| 差异类型 | 数量 | 说明 |
| --- | ---: | --- |
| `modify_comment` | 119 | 106 个缺失注释，加 13 个文本差异 |
| `modify_default` | 5 | 实际库有 server default，ORM 只有 Python 层 default |

5 个默认值差异为 `feishu_connection.custom_attrs` 的 JSON 默认值，以及 `sync_job.execution_count/retry_count/success_count/failure_count` 的 `0`。

Python 层 `default` 与数据库 `server_default` 作用不同。当前 Alembic 环境没有启用默认值比较，但后续启用或使用其他建表入口时，这些差异会造成结构维护不一致。字段注释差异也会干扰自动迁移审查。

字段集合、空值约束、主键、外键、模型声明的普通索引和唯一约束已另行与实际元数据比较，未发现缺失或不一致；Alembic 类型比较未报告类型变更。此结果不覆盖上述已独立查出的表/连接排序规则差异。

0001—0003 的原始建表语句也缺少字段注释，当前依赖后续 0006 补齐；历史脚本及框架表的例外处理需要在项目规范中说明。

### 5. 中优先级：最新迁移无法生成离线 SQL

本次实际运行了不连接数据库的离线生成检查：

| 目标 | 结果 |
| --- | --- |
| `0005_sync_job_ledger` | 通过，生成 22 个 CREATE TABLE（含框架表） |
| `head`，即 0006 | 失败，`NoInspectionAvailable` |

失败位置为 `backend/migrations/versions/0006_column_comments.py:39`。该迁移依赖 `sa.inspect(bind)` 和 `SHOW FULL COLUMNS`，离线模式下的 `MockConnection` 无法提供这些元数据。因此无法按当前完整迁移链生成供审查的离线 SQL。

本机库已经记录为 0006，并不消除这个独立的交付缺陷。后续需要提供可审查的确定性 DDL，或者明确依赖预检元数据的生成流程与验证方式。

### 6. 中优先级：就绪探针不能验证迁移是否为当前版本

`backend/app/persistence/database.py:18` 只执行 `SELECT 1` 与 `SELECT version_num FROM alembic_version LIMIT 1`，没有读取、比较结果，也未校验业务表结构。

本次 `/health/live` 与 `/health/ready` 均返回 HTTP 200；同时通过独立数据库查询确认当前确实是 0006。探针的 `schema=reachable` 只证明版本表可查询，不能单独证明迁移已完成、业务初始化已完成或同步工作正常。

### 7. 需要归档的项目差异与运维证据

- 模型使用稳定字符串标识/复合主键、10 组既有外键、`created_at/updated_at` 及应用维护 UTC 时间。这些与技能通用的自增 INT、禁新增外键、数据库维护时间等基线不同；应通过项目规范记录用途、边界及理由，再决定是否调整。
- 现有索引多用 `ix_` / `uq_`，布尔字段为 MySQL 有符号 tinyint，部分字段未采用 `is_` 前缀；属于规则差异，不能直接等同于当前数据故障。
- 本次所有业务表字段数不超过 30，字符串长度不超过 255，没有 FLOAT/DOUBLE；存在 5 个 TEXT、7 个 JSON 字段，其用途包括说明、设置值、事件载荷和审计快照。
- `README.md`、`docs/运行与验收.md` 仍保留早期“数据库未提供”和旧测试结果；与本次本机已有 MySQL 的事实不同。历史记录不能作为当前环境验收证据。
- 备份恢复说明存在，但本次没有验证实际备份文件、定时备份任务或恢复演练。当前环境可连接，不等于灾难恢复已验收。

## 查询计划与验证结果

对任务认领、事件认领和员工首页查询执行了只读 EXPLAIN：

| 查询 | 当前计划 | 结论边界 |
| --- | --- | --- |
| 按状态认领任务，按创建时间/ID 排序 | `ref`，使用 `ix_sync_job_status`，`Using filesort` | 目前只有 2 个任务；不足以判定性能故障 |
| 按状态认领事件，按接收时间/ID 排序 | `ref`，使用 `ix_event_inbox_status`，`Using filesort` | 事件表为空，后续需要真实数据量评估排序索引 |
| 活跃员工按 ID 分页 | `index`，使用 PRIMARY | 员工表为空，不能作为容量或延迟验收 |

`backend/tests/test_mysql_schema.py` 的 2 项测试通过。pytest 提示缓存目录写入权限告警，不影响测试结果；这些测试仅覆盖部分 MySQL DDL 编译和会话关联约束，未覆盖本报告发现的迁移回退、注释一致性及完整离线生成问题。

未执行写入型 MySQL 集成测试、迁移/回退演练、备份恢复、并发压测或真实飞书同步验收。检查任务的结果是问题清单及证据，不代表上述问题已经修复。

## 在其他已授权环境复核的只读 SQL

以下查询需要先使用该环境的正确连接选择目标数据库。它们只读取版本与结构，不执行 DDL 或 DML。

```sql
SELECT VERSION() AS mysql_version, DATABASE() AS database_name,
       @@character_set_database AS database_charset,
       @@collation_database AS database_collation,
       @@character_set_connection AS connection_charset,
       @@collation_connection AS connection_collation,
       @@session.time_zone AS session_time_zone,
       @@system_time_zone AS system_time_zone,
       @@session.transaction_isolation AS transaction_isolation,
       @@foreign_key_checks AS foreign_key_checks,
       @@session.sql_mode AS sql_mode;

SELECT version_num FROM alembic_version;

SELECT TABLE_NAME, ENGINE, TABLE_COLLATION, TABLE_COMMENT
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME;

SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
       COLUMN_DEFAULT, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME,
       COLUMN_COMMENT, GENERATION_EXPRESSION
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME, ORDINAL_POSITION;

SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, SUB_PART
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;

SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME,
       REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION;

SELECT id, data_version, initialization_status, coverage_status, last_full_sync_at
FROM dataset_state;
```

本次本机检查的辅助脚本和脱敏元数据保存在被 Git 忽略的 `.cache/database-audit-2026-10-21/`；其中 `inspect_database.py` 的连接映射仅适用于本次核对过的本机 Compose，不作为生产通用检查入口。
