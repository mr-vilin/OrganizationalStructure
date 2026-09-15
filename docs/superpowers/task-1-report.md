# Task 1 后端核心实施报告

日期：2026-09-15

## 结果

已建立可导入的 `app.main:app`、MySQL 8 数据模型与 Alembic 初始迁移、组织与门店领域规则、公共读取和管理接口、持久会话/API 凭据/白名单服务、门店事务服务及持久同步任务边界。生产 HTTP 依赖只使用 MySQL 服务；测试中的内存服务仅用于纯领域行为。

飞书 OAuth、事件 SDK、远程采集与同步发布处理器属于 Task 2 接入范围。当前没有生产 dev-login 或绕过身份校验的路径。

## TDD 证据

严格按 RED → GREEN 分组实施：

1. 首批领域、身份、游标、任务、HTTP 与 DDL 测试先运行。最初系统 Python 缺少 pytest，该次属于环境错误，不计为 RED；建立 `backend/.venv` 后重新运行，5 个模块均因 `ModuleNotFoundError: No module named 'app'` 失败，确认生产接口尚不存在。
2. 实现最小模块后运行，得到 `14 passed, 1 failed`。唯一失败为机器凭据调用管理写接口得到 403；原因是 CSRF 比管理员身份更早检查。调整依赖顺序后得到 16 passed。
3. 门店修改规则测试先因 `No module named 'app.stores'` 失败；实现规范化、虚拟根/失效检查和大小写敏感编码冲突后 3 passed。
4. 管理路由契约测试先报告 9 条路由缺失；实现门店、日志、白名单和 API 客户端路由后通过。
5. 针对白名单删除与会话留痕，DDL 测试先因 `FOREIGN KEY(open_id)` 失败；移除该外键并保留大小写敏感索引后通过。删除流程在同一事务先撤销活动会话再删除白名单，认证每次 inner join 当前白名单。

最终验证：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
21 passed, 1 warning in 0.63s
```

唯一警告来自 Starlette TestClient 对 AnyIO 旧类型别名的依赖级弃用提示，不影响测试行为。

```text
backend\.venv\Scripts\python.exe -m compileall -q backend\app backend\migrations
exit 0

cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
exit 0
```

Alembic 离线输出确认业务表均生成 `ENGINE=InnoDB CHARSET=utf8mb4`，来源 ID、事件 ID、会话 ID、客户端 ID 和门店编码使用 `utf8mb4_bin`。

## 实现范围

### 领域与门店

- 每条有效部门关系向上寻找最近有效门店，跨关系去重。
- 主门店只从员工唯一主部门解析，不使用第一条关系或兼职门店补值。
- 明确区分 `resolved`、`not_in_store`、`unknown`、`inconsistent`、`inactive`。
- 缺失祖先和部门环不会无限遍历；缺失祖先产生 unknown。
- 门店编码去首尾空格、空串转 null、大小写敏感；历史编码永久保留给原部门。
- 虚拟根及失效部门不能新设门店。
- 批量 apply 锁定 `dataset_state`，同事务写门店、编码保留、员工门店投影、变更日志和版本；无实际变化不增加版本。

### 身份与权限

- `ORG_` 前缀配置，无 session secret 默认值。
- 无配置时 `/health/live` 可用；`/health/ready` 分别报告未配置、不可达和迁移表可读。
- API secret 使用 scrypt 加 pepper 哈希；创建和轮换仅返回一次明文。
- 管理会话持久化、可撤销、有过期时间和 CSRF HMAC；OAuth 适配器可调用 `SqlIdentityRepository.create_session()`。
- 每次管理认证查询当前数据库白名单；删除白名单立即撤销该身份会话。
- 初始管理员通过 `system_setting.admin_allowlist_initialized` 只初始化一次；重启不会恢复已删除条目。
- 管理读接口只接受会话，管理写接口再验证 CSRF；机器凭据仅可访问 `/api/v1`。
- 参数验证错误只回传 `loc/type/msg`，不回显输入值，避免 OAuth code 或秘密出现在响应。

### 查询与任务

- 公共 8 个读端点及相同字段的管理端读别名。
- 部门树支持根及递归后代；员工部门查询支持 `include_descendants` 并去重。
- 同时传 `store_id` 与 `primary_store_id` 使用独立子查询，不产生同表重复 join。
- 门店返回路径、全部归属人数和主归属人数；员工返回关系、全部门店和主状态。
- 不透明 HMAC 游标绑定资源、筛选、世代、版本和最后 ID；筛选不符返回 400，版本变化返回 409。
- MySQL 使用 `REPEATABLE READ`，每次列表读取在事务快照内读取状态与事实。
- 同步任务持久提交、同范围活动任务复用、`SKIP LOCKED` 认领、租约代次校验、失败重试、列表及详情 API 已实现。

## 文件表

| 路径 | 内容 |
| --- | --- |
| `backend/pyproject.toml` | Python 工程和精确直接依赖 |
| `backend/requirements.lock` | 包含传递依赖的完整环境锁，含 PyMySQL RSA/cryptography |
| `backend/app/config.py` | `ORG_` 配置与身份就绪判定 |
| `backend/app/main.py` | FastAPI、错误 envelope、健康、公共读取、同步任务与会话撤销 |
| `backend/app/admin/router.py` | 管理读取、门店、日志、白名单、API 客户端接口 |
| `backend/app/directory/domain.py` | 组织关系与主门店派生 |
| `backend/app/stores/domain.py` | 门店修改规范化与校验 |
| `backend/app/stores/service.py` | 门店预览和原子 apply |
| `backend/app/identity/services.py` | 纯领域会话/API 凭据行为 |
| `backend/app/public_api/cursor.py` | 签名版本游标 |
| `backend/app/sync/services.py` | 纯任务状态领域行为 |
| `backend/app/sync/worker.py` | Task 2 的 worker 模块入口 |
| `backend/app/persistence/models.py` | 组织事实、派生、身份、事件、任务、暂存、日志模型 |
| `backend/app/persistence/database.py` | MySQL 引擎、REPEATABLE READ 与 readiness |
| `backend/app/persistence/repositories.py` | 持久身份与任务仓储 |
| `backend/app/persistence/read_service.py` | 一致读、筛选、递归部门及分页实现 |
| `backend/migrations/**` | Alembic 配置与初始迁移 |
| `backend/tests/**` | 21 个领域、权限、契约和 MySQL DDL 测试 |
| `docs/backend-api.md` | 前端、下游与 Task 2 接口契约 |

## 接口关注点

- 所有成功响应为 `{data, meta}`，错误为 `{error:{code,message}}`；字段级错误在 `error.fields`。
- 列表调用方必须原样使用 `next_cursor`，不可解析游标；跨端点整轮拉取要传同一 epoch/version。
- 管理门店 apply 必须使用 preview 对应的 `data_version`；409 后重新 preview。
- `client_id` 与 `secret` 通过点号组成 Bearer 值；保存后的 API client 响应不含 secret/hash。
- `org_session` Cookie 保存不透明数据库会话 ID；Task 2 回调需设置 HttpOnly、Secure、SameSite=Lax，并把 CSRF 明文交给前端内存态。
- HTTP 启动参数应关闭 access log，避免 OAuth code 进入访问日志。

## 未验证与后续接入

- 用户已确认稍后提供数据库，因此未连接真实 MySQL，也未声称完成事务、锁等待、死锁、租约竞争、字符集服务器配置或备份恢复验收。SQLite 未用于替代。
- Alembic 只完成 MySQL 方言离线 DDL 编译；真实迁移、readiness、caching_sha2_password、连接池和 REPEATABLE READ 需在目标 MySQL 验证。
- 飞书真实权限、分页、orders、OAuth 身份映射、事件去重和远程失败恢复属于 Task 2 与企业联调。
- `python -m app.sync.worker` 当前只提供稳定入口与仓储边界，Task 2 需注入飞书采集/发布处理循环后再作为生产 worker 运行。
- 批量门店投影当前采用全量重建以保证正确性；真实规模验收后应测量锁时间，必要时改为受影响子树增量重算，保持同一事务语义。

## 轮 1 评审修复（2026-09-15）

已修复 `task-1-review.md` 的 8 项 Important 与 2 项 Minor：

- 持久会话查询改为显式 `AdminAllowlist.open_id == AdminSession.open_id` JOIN，并通过 MySQL 方言编译测试。
- 门店 PATCH 使用 `UNSET` 区分省略与显式 null；只切换标记或只改一项资料不会清空另一项，取消门店保留编码和备注。preview 返回合并后的具体值，不暴露内部 sentinel。
- API 凭据轮换下沉到单个仓储事务：锁旧记录、创建新记录、撤销旧记录、写脱敏日志一起提交，异常由事务回滚。
- `0001_initial` 不再导入可变 `Base.metadata`，全部表、索引、外键和 downgrade 均为冻结的显式 Alembic 操作。
- 公共及管理门店员工列表均接受 `dataset_epoch/data_version`，支持跨端点一致读取。
- 白名单和 API 客户端全部写操作使用事务服务，并在同一事务写不含 secret/hash 的 ChangeLog。
- 新增 UTC 序列化边界，覆盖状态、任务、日志、白名单与客户端时间。
- 初始迁移种下 pending `dataset_state` 与独立 `system_setting.task_queue_lock`。任务提交锁定后者，不依赖初始化完成，也不会出现首次同步循环依赖。
- `open_id`、部门 ID 和客户端名称增加去空格后的非空与长度校验。
- 任务列表增加稳定 `(created_at,id)` 游标和 `limit+1` 分页。

针对性 RED 证据包括：评审测试首次因缺少 `UNSET` 无法收集；迁移前持久会话 JOIN 编译复现 `InvalidRequestError`；门店员工端点缺版本参数、管理别名和任务 cursor 的 OpenAPI 断言失败。修复后针对性测试 `8 passed`。

轮 1 最终回归：

```text
backend\.venv\Scripts\python.exe -m pytest backend\tests -q
26 passed, 1 warning

backend\.venv\Scripts\python.exe -m compileall -q backend\app backend\migrations
exit 0

cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head --sql
exit 0；输出含两条单例种子 INSERT，全部业务表仍为 InnoDB/utf8mb4
```

真实 MySQL 尚未提供，因此凭据轮换失败注入回滚、并发首次任务复用和迁移实跑仍属于真实 MySQL 验收项；代码路径均使用数据库事务与行锁，没有使用 SQLite 冒充验证。
