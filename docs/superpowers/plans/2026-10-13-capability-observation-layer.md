# Capability and Observation Layer Implementation Plan

**For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 在现有组织服务中建立可被 HTTP 和 MCP 共同调用的业务能力层、观察层和操作回执，保留现有 API 行为并为 Agent 评估提供独立证据。

**Architecture:** 以现有 ReadService、StoreAdminService、SqlSyncJobRepository 和 Publisher/Worker 为业务实现，新增 Capability Contract 统一输入输出、权限和错误映射；新增 OperationReceipt 记录一次 Agent 操作与任务、数据版本和审计的关联。现有管理 API 逐步改为调用能力层，MCP 通过内部能力 HTTP 边界访问它。

**Tech Stack:** Python 3.11+、FastAPI 0.116.1、Pydantic、SQLAlchemy 2.0、Alembic、PyMySQL、pytest、MySQL 8.4。

**Spec:** docs/architecture/agent-native-requirements-clarification.md

## Global Constraints

- 飞书是部门、员工和组织关系的权威来源；本地只写门店标记、编码和备注。
- 不新增创建、移动、删除飞书组织或员工的能力。
- 现有公共 API 和管理 API 的 data/meta 与 error envelope 保持兼容。
- 观察层状态不替换当前 SyncJob 的 queued、running、succeeded、failed。
- data_version 和 dataset_epoch 必须继续绑定一致读、游标和 409 DATASET_CHANGED。
- 事实、门店投影、变更日志、操作回执和版本必须在同一业务事务中提交或整体回滚。
- 新数据库表和字段必须使用 InnoDB、utf8mb4，并为每个字段提供准确中文 COMMENT。
- 不在代码、日志、回执和测试报告中输出数据库密码、飞书 token、API secret 或 OAuth 原文。
- MySQL 集成测试只允许连接名称以 _test 结尾的独立数据库。
- 本计划只处理能力与观察层；MCP 工具实现见 2026-10-13-mcp-adapter-policy.md，Evaluation 与 CI 见 2026-10-13-agent-evaluation-ci.md。

---

## 范围与文件地图

### 新建文件

- backend/app/capabilities/__init__.py：能力层公开入口。
- backend/app/capabilities/contracts.py：AgentContext、Observation、CapabilityResult 和输入类型。
- backend/app/capabilities/errors.py：能力层错误码和异常映射。
- backend/app/capabilities/receipts.py：OperationReceipt 的仓储和幂等查询。
- backend/app/capabilities/observations.py：任务、数据质量、版本和审计的观察结果组装。
- backend/app/capabilities/service.py：OrganizationCapabilities 门面。
- backend/app/capabilities/router.py：供独立 MCP 适配层调用的受保护内部 HTTP 边界。
- backend/migrations/versions/0007_operation_receipt.py：操作回执表迁移。
- backend/tests/test_capability_contract.py：能力输入输出和错误契约测试。
- backend/tests/test_operation_receipt.py：回执、幂等和状态测试。
- backend/tests/test_capability_router.py：内部能力 HTTP 契约测试。
- backend/tests/test_capability_integration.py：能力与现有服务的 SQLite 事务测试。
- backend/tests/integration/test_capability_mysql.py：真实 MySQL 锁、唯一键和回滚测试。

### 修改文件

- backend/app/persistence/models.py：增加 OperationReceipt ORM 模型。
- backend/app/dependencies.py：在 Runtime 中提供能力门面和内部服务鉴权依赖。
- backend/app/config.py：增加内部能力服务 token 的 SecretStr 配置。
- backend/app/main.py：注册内部能力 router。
- backend/app/admin/router.py：将同步、门店预览和应用路径改为调用能力门面。
- .env.example、docs/backend-api.md、docs/运行与验收.md：补充配置和契约说明。

## 固定接口

后续 MCP 和 Evaluation 计划依赖以下类型和方法名称。

~~~python
@dataclass(frozen=True)
class AgentContext:
    actor_type: Literal["human_agent", "ci_agent"]
    actor_id: str
    environment: Literal["production", "test"]
    run_id: str | None = None
    case_id: str | None = None
    approved: bool = False

@dataclass(frozen=True)
class Observation:
    execution: Literal[
        "request_recorded", "accepted", "running", "submitted",
        "verified", "partial", "failed", "unconfirmed"
    ]
    fact_quality: Literal[
        "resolved", "partial", "unknown", "inconsistent", "not_applicable"
    ]
    dataset_epoch: str | None
    data_version: int | None
    next_action: str | None
    evidence: dict[str, Any]

@dataclass(frozen=True)
class CapabilityResult(Generic[T]):
    operation_id: str | None
    data: T
    observation: Observation
    audit: dict[str, Any]
~~~

OrganizationCapabilities 至少提供 status、find_departments、get_department、list_employees、get_employee、list_stores、get_store、list_store_employees、get_change_logs、get_sync_job、preview_store_changes、apply_store_changes、request_sync 和 retry_sync_job；写方法必须接收 idempotency_key，应用门店修改必须接收 expected_version。

### Task 1: 固定能力契约和错误行为

**Files:**
- Create: backend/app/capabilities/contracts.py
- Create: backend/app/capabilities/errors.py
- Create: backend/tests/test_capability_contract.py

**Interfaces:**
- Consumes: 现有 ReadService、StorePatch、JobService 和公共错误码。
- Produces: AgentContext、Observation、CapabilityResult、能力错误码和序列化规则。

- [ ] **Step 1: Write the failing contract tests**

~~~python
def test_store_apply_result_contains_operation_and_observation():
    result = CapabilityResult(
        operation_id="op_1",
        data={"changed_count": 1},
        observation=Observation(
            execution="submitted",
            fact_quality="resolved",
            dataset_epoch="epoch_a",
            data_version=43,
            next_action=None,
            evidence={"change_log_ids": ["log_1"]},
        ),
        audit={"actor_id": "agent_1"},
    )
    assert result.to_dict()["observation"]["data_version"] == 43
~~~

增加未知状态、非法 environment、写能力缺少 operation_id 和错误码序列化测试。

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capability_contract.py -q

Expected: FAIL because the capability package and contract types do not exist.

- [ ] **Step 3: Implement the immutable contract types**

使用 dataclass、Literal 和 TypeVar；to_dict() 只返回 JSON 可编码值。errors.py 定义 CapabilityError、ConfirmationRequired、OperationNotFound、CapabilityNotAllowed、OperationConflict，并绑定稳定 code、HTTP status 和 message。

- [ ] **Step 4: Run the focused tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capability_contract.py backend/tests/test_http_contract.py -q

Expected: PASS；现有 HTTP 错误 envelope 不回归。

- [ ] **Step 5: Commit the contract boundary**

~~~powershell
git add backend/app/capabilities/contracts.py backend/app/capabilities/errors.py backend/tests/test_capability_contract.py
git commit -m "feat: define organization capability contracts"
~~~

### Task 2: 增加操作回执模型和迁移

**Files:**
- Modify: backend/app/persistence/models.py
- Create: backend/migrations/versions/0007_operation_receipt.py
- Create: backend/tests/test_operation_receipt.py
- Create: backend/tests/test_mysql_schema_agent.py

**Interfaces:**
- Consumes: Task 1 的类型和现有 DatasetState、SyncJob、ChangeLog。
- Produces: OperationReceipt ORM 模型、迁移 revision 0007 和回执唯一键约束。

- [ ] **Step 1: Write failing model and DDL tests**

~~~python
def test_operation_receipt_ddl_is_innodb_utf8mb4_and_has_chinese_comments():
    ddl = str(CreateTable(OperationReceipt.__table__).compile(dialect=mysql.dialect()))
    assert "ENGINE=InnoDB" in ddl
    assert "CHARSET=utf8mb4" in ddl
    assert "操作回执" in ddl
~~~

测试还要验证同一 actor_id、environment、idempotency_key 不能出现两条回执，operation_id 是主键，job_id、case_id、status 有索引。

- [ ] **Step 2: Run the tests and verify they fail**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_operation_receipt.py backend/tests/test_mysql_schema_agent.py -q

Expected: FAIL because OperationReceipt and migration 0007 do not exist.

- [ ] **Step 3: Add the ORM model with field comments**

增加 operation_id、idempotency_key、capability、actor_type、actor_id、environment、run_id、case_id、request_hash、status、job_id、before_epoch、before_version、committed_epoch、committed_version、result_summary、error_code、created_at、updated_at。每个 mapped_column 必须有准确中文 comment；表参数使用现有 TABLE_ARGS。

- [ ] **Step 4: Add migration 0007**

使用 revision 0007_operation_receipt、down_revision 0006_column_comments。为每个字段提供中文 comment；创建唯一约束和 job_id、case_id、status、created_at 索引；downgrade 先删索引和表；不修改已有表。

- [ ] **Step 5: Validate offline SQL**

~~~powershell
Push-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head --sql | Out-File -Encoding utf8 ..\tmp-agent-migration.sql
Pop-Location
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_operation_receipt.py backend/tests/test_mysql_schema_agent.py -q
~~~

Expected: SQL 和模型测试 PASS，且包含 InnoDB、utf8mb4 和中文字段注释。

- [ ] **Step 6: Commit the persistence boundary**

~~~powershell
git add backend/app/persistence/models.py backend/migrations/versions/0007_operation_receipt.py backend/tests/test_operation_receipt.py backend/tests/test_mysql_schema_agent.py
git commit -m "feat: add agent operation receipts"
~~~

### Task 3: 实现回执仓储与观察组装

**Files:**
- Create: backend/app/capabilities/receipts.py
- Create: backend/app/capabilities/observations.py
- Modify: backend/tests/test_operation_receipt.py
- Create: backend/tests/test_capability_integration.py

**Interfaces:**
- Consumes: OperationReceipt、DatasetState、SyncJob、SyncJobDetail、ChangeLog。
- Produces:

~~~python
class ReceiptRepository:
    def get_by_idempotency(self, db, actor_id, environment, idempotency_key): ...
    def create(self, db, context, capability, idempotency_key, request_hash, now): ...
    def mark_accepted(self, db, operation_id, job_id, epoch, version, summary, now): ...
    def mark_submitted(self, db, operation_id, epoch, version, summary, audit_ids, now): ...
    def mark_failed(self, db, operation_id, error_code, summary, now): ...
~~~

ObservationService 至少提供 observation_for_status、observation_for_job 和 observation_for_commit。

- [ ] **Step 1: Write failing repository tests**

覆盖首次创建、同幂等键返回原回执、不同 request_hash 拒绝复用、提交版本写入、失败错误码写入和事务回滚不留回执。

- [ ] **Step 2: Run the focused tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_operation_receipt.py backend/tests/test_capability_integration.py -q

Expected: FAIL because repository and observation service are not implemented.

- [ ] **Step 3: Implement transaction-safe repository methods**

方法接收调用方已经打开的 SQLAlchemy Session，不自行提交事务。幂等查询使用唯一键；request_hash 不一致时抛出 OperationConflict；状态更新使用行锁，避免并发完成同一 idempotency_key。

- [ ] **Step 4: Implement observation mapping**

queued 映射为 accepted，running 映射为 running，succeeded 映射为 submitted，failed 映射为 failed；存在 SyncJobDetail 失败或 PendingFact 时将 submitted 映射为 partial；无法读取状态时返回 unconfirmed。版本来自同一 DatasetState 读取。

- [ ] **Step 5: Run regression tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_operation_receipt.py backend/tests/test_capability_integration.py backend/tests/test_sync_persistence.py -q

Expected: PASS；事实、投影、日志和版本回滚行为不变。

### Task 4: 实现 OrganizationCapabilities 门面

**Files:**
- Create: backend/app/capabilities/service.py
- Modify: backend/app/dependencies.py
- Modify: backend/app/config.py
- Modify: backend/tests/test_capability_integration.py

**Interfaces:**
- Consumes: SqlReadService、StoreAdminService、SqlSyncJobRepository、ReceiptRepository、ObservationService。
- Produces: 固定接口中的 OrganizationCapabilities 方法。

- [ ] **Step 1: Write failing facade tests**

~~~python
def test_apply_store_changes_requires_confirmation_for_production_agent(runtime):
    context = AgentContext("human_agent", "agent_1", "production", approved=False)
    with pytest.raises(ConfirmationRequired):
        runtime.capabilities.apply_store_changes(
            context, [StorePatch("dep_a", True)], 1, "store-a-1", None
        )
~~~

增加 test 环境 ci_agent 可应用、production ci_agent 被拒绝、preview 不改版本、活动同步任务复用、失败任务可重试和待核实结果正确映射测试。

- [ ] **Step 2: Run facade tests and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capability_integration.py -q

Expected: FAIL because OrganizationCapabilities 和 Runtime.capabilities 不存在。

- [ ] **Step 3: Implement read and write methods**

查询方法委托 SqlReadService，并补充按名称/路径的 find_departments；名称不唯一返回 AMBIGUOUS_TARGET。preview 委托 StoreAdminService.preview；apply 在回执事务内校验幂等、版本和确认，再调用 StoreAdminService.apply；同步方法调用 jobs.submit/retry 并写 accepted 回执。

- [ ] **Step 4: Implement policy checks**

L0/L1 不要求 approved；生产 L2 没有 approved 或有效 approval_token 时抛出 ConfirmationRequired；test 环境 ci_agent 仅允许 test 数据库和 test run_id；操作者来自 AgentContext。

- [ ] **Step 5: Run all backend tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests -q

Expected: 现有测试和能力层测试全部通过；无真实 MySQL 时按既有规则明确 skip。

- [ ] **Step 6: Commit the facade**

~~~powershell
git add backend/app/capabilities/service.py backend/app/dependencies.py backend/app/config.py backend/tests/test_capability_integration.py
git commit -m "feat: expose organization capabilities"
~~~

### Task 5: 增加受保护的内部能力 HTTP 边界

**Files:**
- Create: backend/app/capabilities/router.py
- Modify: backend/app/main.py
- Modify: backend/app/dependencies.py
- Modify: .env.example
- Create: backend/tests/test_capability_router.py
- Modify: docs/backend-api.md

**Interfaces:**
- Consumes: OrganizationCapabilities 和 AgentContext。
- Produces: /internal/capabilities 下供 MCP sidecar 使用的 JSON API；这些接口不是下游公共 API。

- [ ] **Step 1: Write failing HTTP tests**

覆盖缺 service token、production L2 未确认、只读查询、请求体 actor 被忽略、版本冲突和秘密过滤。

- [ ] **Step 2: Run HTTP tests and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capability_router.py -q

Expected: FAIL because internal router and service-token dependency do not exist.

- [ ] **Step 3: Add internal service authentication**

config.py 增加 agent_service_token: SecretStr | None；dependencies.py 使用 hmac.compare_digest 校验 Bearer token，从受保护请求头读取 actor_id、environment、run_id、case_id、approved。缺 token 或环境不匹配返回 AGENT_SERVICE_UNAUTHORIZED。

- [ ] **Step 4: Add and register the router**

router 提供 status、部门、员工、门店、日志、任务、preview/apply store changes、request/retry sync 端点；只负责 Pydantic 解析、Context 构建和能力调用。main.py 注册该 router。

- [ ] **Step 5: Run security and compatibility tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_capability_router.py backend/tests/test_http_contract.py -q

Expected: PASS；公共 API、管理员会话和只读机器凭据行为不回归。

- [ ] **Step 6: Update internal API documentation**

docs/backend-api.md 说明内部边界必须网络隔离和服务 token，不记录 token 值，也不宣称内部路由为公共契约。

### Task 6: MySQL 验收和文档闭环

**Files:**
- Create: backend/tests/integration/test_capability_mysql.py
- Modify: docs/运行与验收.md
- Modify: deploy/README.md
- Modify: README.md

**Interfaces:**
- Consumes: Task 1～5 的能力、回执、迁移和内部接口。
- Produces: 可重复的 MySQL 集成命令和能力层验收记录。

- [ ] **Step 1: Write MySQL integration tests**

覆盖两个并发 apply 只有一个版本提交、相同幂等键返回同一 operation_id、审计失败整体回滚、任务回执与 SyncJob 一致、旧世代回执不能伪装为当前版本。

- [ ] **Step 2: Start disposable MySQL and migrate**

~~~powershell
docker compose -f deploy/compose.mysql-test.yaml up -d --wait
$env:ORG_TEST_DATABASE_URL = "mysql+pymysql://organization_test:local-integration-only@127.0.0.1:13306/organization_test?charset=utf8mb4"
Push-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
~~~

- [ ] **Step 3: Run MySQL tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/integration/test_capability_mysql.py -q

Expected: all tests PASS；没有测试数据库时明确 skip。

- [ ] **Step 4: Update acceptance docs**

docs/运行与验收.md 增加能力层回执、观察状态、内部服务鉴权和 MySQL 运行记录；deploy/README.md 增加 token 配置名和 sidecar 网络边界；README.md 只增加链接，不宣称真实 Agent 或飞书验收已完成。

- [ ] **Step 5: Run complete backend verification**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests -q

Expected: existing backend tests PASS，并独立记录 MySQL 集成结果。

- [ ] **Step 6: Commit the capability subsystem**

~~~powershell
git add backend/app/capabilities backend/app/persistence/models.py backend/app/dependencies.py backend/app/config.py backend/app/main.py backend/app/admin/router.py backend/migrations/versions/0007_operation_receipt.py backend/tests docs/backend-api.md docs/运行与验收.md deploy/README.md README.md .env.example
git commit -m "feat: add observable organization capability layer"
~~~

## Verification Checklist

- [ ] 现有公共 API 的 envelope、版本和错误码保持兼容。
- [ ] 生产人工 Agent 的 L2 写操作没有确认时必定被拒绝。
- [ ] test 环境 ci_agent 不能访问 production 数据库。
- [ ] 同一幂等键不会产生第二次业务提交。
- [ ] data_version 无业务变化不增加。
- [ ] 待核实事实不会被映射成删除或离职。
- [ ] 新迁移每个字段都有中文 COMMENT，并使用 InnoDB、utf8mb4。
- [ ] MySQL 集成测试只连接独立 _test 数据库。

