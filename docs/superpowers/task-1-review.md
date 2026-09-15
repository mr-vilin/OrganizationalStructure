# Task 1 审查

### Spec Compliance

- ❌ 存在需求符合性问题：管理员会话认证在当前模型上无法构造 SQL；门店更新会把未提供的历史资料清空；凭据轮换并非原子操作；首版迁移依赖可变的运行时元数据；`/stores/{id}/employees` 缺少跨端点版本参数；白名单与 API 凭据写入没有审计日志。真实 MySQL/飞书联调在实施报告中明确列为未验证，符合“先代码、后联调”的当前约束，但因此不能视为相关验收已完成。
- ⚠️ 无真实 MySQL，无法验证事务隔离、锁等待/死锁、`SKIP LOCKED` 竞争、MySQL 返回时间值以及 Alembic 实际执行。实施报告已如实保留这些未验收项，不把它们本身判为代码缺陷。

### Strengths

- `backend/app/directory/domain.py:33-78` 将“每条关系最近门店”和“主部门唯一派生”分开，实现了 `unknown`、`not_in_store`、`inconsistent`、`inactive` 的区别，并处理缺失祖先和环。
- `backend/app/stores/service.py:26-53` 在同一个数据库事务内锁定版本、写门店资料、重建投影、记录变更日志并递增版本；无实际变化时不增加版本。
- `backend/app/persistence/read_service.py:36-146` 的列表读取在事务中取得状态，游标同时绑定资源、筛选、世代、版本和最后 ID，版本变化会被拒绝。
- `backend/app/dependencies.py:41-67` 明确隔离机器凭据与管理员 Cookie，并对管理写入增加 CSRF；`backend/app/main.py:26-35` 保留业务字段错误且过滤 Pydantic 输入值，避免敏感输入回显。
- `backend/app/persistence/repositories.py:86-150` 提供了数据库任务仓储、活动任务复用、`SKIP LOCKED` 认领、租约代次校验和失败重试，生产依赖使用该持久实现。

### Issues

#### Critical (Must Fix)

- 无。

#### Important (Should Fix)

1. `backend/app/persistence/repositories.py:27-34`：`authenticate_session()` 使用 `select(AdminSession).join(AdminAllowlist)`，但两张表之间已经没有外键或 ORM relationship，SQLAlchemy 无法推断 `ON` 条件。最小 MySQL 方言编译实际抛出 `InvalidRequestError: Don't know how to join to ... AdminAllowlist`，因此任何带管理员会话的请求都会在认证阶段变成 500，管理员功能整体不可用。应显式写成 `.join(AdminAllowlist, AdminAllowlist.open_id == AdminSession.open_id)`，并补一个针对持久仓储查询构造/认证行为的测试。

2. `backend/app/admin/router.py:64-77`、`backend/app/stores/service.py:31-47`：`StoreChange` 把 `store_code` 和 `notes` 的缺省值都解释为 `None`，服务随后把它们完整覆盖到现有 `StoreProfile`。因此仅切换 `is_store` 或只修改其中一个资料字段，会意外清空另一个字段；取消门店标记也会丢掉要求保留的历史编码/备注。应区分“字段未提供”和“显式 null”，在读取现值后合并 patch；取消标记时保留资料，并为这三种行为增加测试。

3. `backend/app/admin/router.py:174-184`、`backend/app/persistence/repositories.py:64-77`：轮换客户端凭据分成“读取旧记录”“提交撤销”“提交创建”三个事务。创建新凭据失败时旧凭据已经永久失效，不满足凭据轮换的原子性。应由仓储提供一个事务内锁定旧记录、生成并写入新记录、撤销旧记录的 `rotate` 操作，并以失败回滚测试验证旧凭据仍可用。

4. `backend/migrations/versions/0001_initial.py:3-20`：已发布的初始 revision 在执行时导入当前 `Base.metadata` 并 `create_all/drop_all`。后续模型新增表或字段会悄悄改变 `0001_initial` 的含义，使新数据库提前获得未来结构，之后增量迁移可能重复建表/列；降级也会删除届时所有模型表。首版迁移必须冻结为显式 `op.create_table`/索引/外键及对应显式 downgrade，后续结构只能进入新 revision。

5. `backend/app/main.py:133-135`：员工、部门、门店列表都接受 `dataset_epoch` 和 `data_version`，但门店员工列表只接受 `cursor`。这使调用方无法按文档要求把首页版本传给另一个端点的首个请求，跨端点一致读取无法建立；其管理端也没有对应的门店员工别名。应为该端点透传世代/版本，并让所有参与同一轮读取的列表接口保持相同契约。

6. `backend/app/admin/router.py:136-190`：白名单添加/删除以及 API 客户端创建/轮换/撤销都直接修改安全配置，却没有在同一事务写 `ChangeLog`；现有日志仅在门店服务 `backend/app/stores/service.py:47` 写入。这会丢失关键管理操作的操作者、前后状态和提交时间，无法满足日志与安全管理的审计需求。应将这些写操作下沉到事务服务，在同一事务写脱敏日志（绝不记录 secret 或 hash）。

7. `backend/app/persistence/models.py:22,109,118-119,128-129,143,146-147,182`、`backend/app/admin/router.py:121-184`：MySQL 的 `DATETIME` 不保存时区信息，SQLAlchemy 从 MySQL 取回这些字段通常是 naive `datetime`；路由直接交给 FastAPI 序列化，会输出没有 `Z`/偏移的字符串，浏览器将其当本地时间。契约示例要求 UTC `Z`，并且部署设计要求 UTC 存储、北京时间展示。应在响应 DTO/序列化边界明确把数据库 naive UTC 补为 `timezone.utc`，并覆盖任务、日志、白名单、客户端和状态时间字段。

8. `backend/app/persistence/repositories.py:94-112`：任务复用依赖先锁 `dataset_state`，但未检查该单例行是否存在；初始化前该查询返回 `None` 时不会形成串行锁，而 `sync_job` 也没有能表达“同范围仅一个活动任务”的唯一约束。两个并发首次提交可能各自插入 queued 任务，破坏复用语义。应在允许提交前保证并验证状态单例存在，或使用专门的稳定锁行/可由数据库约束和冲突处理保证的方案。

#### Minor (Nice to Have)

- `backend/app/admin/router.py:125-142,157-171`：`open_id` 只声明为任意字符串，客户端名称虽有 `min_length=1`，但仓储 `strip()` 后可能变为空字符串。建议对来源 ID 和名称在规范化后设置非空、合理长度限制，避免无效管理记录。
- `backend/app/main.py:153-162`：任务列表只有 `limit`，没有游标；当任务超过上限时旧任务不可访问。若该列表属于“所有列表固定分页”的产品约束，应加入稳定的 `(created_at, id)` 游标。

### Checks Run

- 仅运行了一个针对具体疑点的 SQLAlchemy MySQL 方言编译检查：`select(AdminSession).join(AdminAllowlist)`；结果稳定复现 `InvalidRequestError`。未重复运行完整测试套件。
- 对照实施报告检查了未验证声明：真实 MySQL 事务/迁移/并发以及真实飞书均明确列为未验收，报告没有伪称已完成联调。

### Assessment

**Task quality:** Needs fixes

**Reasoning:** 领域规则、版本游标和持久任务边界已有扎实骨架，但管理员认证当前会直接失败，且资料保留、凭据轮换原子性、迁移冻结和安全审计存在合并前必须修复的缺陷。修复后仍需按报告计划在真实 MySQL 上完成事务与迁移验收。
