# Agent Evaluation and CI Implementation Plan

**For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans，按任务实施；用复选框跟踪完成情况。

**Goal:** 在隔离 MySQL、Fake Feishu 和 MCP 测试身份上建立可重复的 Worker Agent Evaluation，以确定性断言为发布门禁，并为 LLM Judge 保留诊断接口。

**Architecture:** Evaluation Runner 创建用例夹具、启动 Worker Agent、记录 MCP 工具轨迹，并通过独立只读观察路径读取最终事实。确定性 Evaluator 负责硬门槛；Provider Worker 和 LLM Judge 通过协议注入，默认测试使用 scripted worker，真实模型评估在受控夜间或发布前环境运行。

**Tech Stack:** Python 3.11+、pytest、SQLAlchemy、MySQL 8.4、Fake Feishu、MCP client、Pydantic、Docker Compose；不绑定具体 CI 平台。

**Spec:** docs/architecture/agent-native-requirements-clarification.md

## Global Constraints

- 必须先完成 2026-10-13-capability-observation-layer.md 和 2026-10-13-mcp-adapter-policy.md 的能力与 MCP 契约。
- Evaluation 只连接名称以 _test 结尾的 MySQL 数据库。
- Worker Agent 只能通过 MCP 调用，不能直接访问 SQLAlchemy Session、Fake Feishu 或 Evaluator 断言。
- Evaluator 不使用 Worker 的自报结果生成 expected_state。
- 每个用例使用唯一 run_id、case_id 和 Fake Feishu 场景；用例串行执行，结束后清理全部业务数据。
- 数据库 reset 只能作用于测试库；CLI 在数据库名不符合 _test 时直接退出。
- LLM Judge 初期只输出诊断分数，不阻断 CI；硬门槛失败必须阻断。
- 真实飞书不进入普通 CI；真实联调使用专用企业应用、最小权限和独立凭据。
- 测试报告不得包含数据库密码、飞书 token、API secret 或员工敏感原文。

---

## 范围与文件地图

### 新建文件

- backend/app/evaluation/__init__.py
- backend/app/evaluation/models.py
- backend/app/evaluation/cases.py
- backend/app/evaluation/fixtures.py
- backend/app/evaluation/fake_feishu.py
- backend/app/evaluation/worker.py
- backend/app/evaluation/assertions.py
- backend/app/evaluation/runner.py
- backend/app/evaluation/report.py
- backend/app/evaluation/cli.py
- backend/tests/evaluation/test_case_schema.py
- backend/tests/evaluation/test_fake_feishu.py
- backend/tests/evaluation/test_assertions.py
- backend/tests/evaluation/test_runner.py
- backend/tests/evaluation/test_agent_cases.py
- backend/tests/evaluation/cases/*.yaml
- deploy/tests/test_evaluation_runtime.py

### 修改文件

- backend/tests/integration/conftest.py：增加 Evaluation 专用隔离 reset fixture。
- deploy/compose.mysql-test.yaml：保留临时 MySQL，并补充 Evaluation 运行说明。
- docs/运行与验收.md、deploy/README.md、README.md：增加命令和结果口径。

## 固定类型和协议

~~~python
@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    goal: str
    fixture: dict[str, Any]
    allowed_tools: tuple[str, ...]
    expected_state: dict[str, Any]
    forbidden_effects: tuple[dict[str, Any], ...]
    timeout_seconds: int
    max_tool_calls: int

@dataclass(frozen=True)
class ToolTraceEvent:
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    result_code: str | None
    operation_id: str | None
    started_at: str
    finished_at: str

@dataclass(frozen=True)
class AgentRunContext:
    run_id: str
    case_id: str
    actor_id: str
    environment: Literal["test"]

@dataclass(frozen=True)
class AgentRun:
    final_text: str
    trace: tuple[ToolTraceEvent, ...]
    terminal_observation: dict[str, Any]

@dataclass(frozen=True)
class EvaluationReport:
    case_id: str
    run_id: str
    hard_passed: bool
    hard_failures: tuple[str, ...]
    soft_scores: dict[str, float]
    evidence: dict[str, Any]
    trace: tuple[ToolTraceEvent, ...]
~~~

## 六个首批用例

| case_id | 目标 | 初始条件 | 主要断言 |
|---|---|---|---|
| ORG_AGENT_READ_PRIMARY_STORE | 解释员工主门店 | 主部门在人民路店、兼职大学城店 | store_ids 含两店，primary_store_id 为人民路店 |
| ORG_AGENT_READ_NOT_IN_STORE | 解释主部门不在门店 | 主部门在总部、兼职大学城店 | primary_store_id 为空，状态为 not_in_store |
| ORG_AGENT_APPLY_STORE | 把部门标记为门店 | 有效部门、data_version 已知 | 预览后确认应用，投影、版本和日志一致 |
| ORG_AGENT_SYNC_SUBTREE | 更新上海子树 | Fake Feishu 返回多页部门和员工 | 任务到达终态，范围完整，版本和质量符合预期 |
| ORG_AGENT_VERSION_CONFLICT | 处理版本冲突 | 预览后注入一次门店修改 | 收到 DATASET_CHANGED，重新读取后不覆盖新版本 |
| ORG_AGENT_PERMISSION_SHRINK | 处理权限收窄 | Fake Feishu 后续隐藏一个已有对象 | 保留旧事实并标待核实，不标为删除或离职 |

权限边界另由 MCP 契约测试覆盖，只读身份调用写工具不依赖真实模型。

### Task 1: 定义用例 schema 和报告模型

**Files:**
- Create: backend/app/evaluation/models.py
- Create: backend/app/evaluation/cases.py
- Create: backend/tests/evaluation/test_case_schema.py
- Create: backend/tests/evaluation/cases/ORG_AGENT_READ_PRIMARY_STORE.yaml
- Create: backend/tests/evaluation/cases/ORG_AGENT_READ_NOT_IN_STORE.yaml

**Interfaces:**
- Consumes: 六个用例和 MCP 工具目录。
- Produces: EvaluationCase、ToolTraceEvent、EvaluationReport、load_case(path) 和 validate_case(case)。

- [ ] **Step 1: Write failing schema tests**

~~~python
def test_case_requires_goal_expected_state_and_forbidden_effects():
    case = load_case("backend/tests/evaluation/cases/ORG_AGENT_READ_PRIMARY_STORE.yaml")
    assert case.case_id == "ORG_AGENT_READ_PRIMARY_STORE"
    assert case.goal
    assert case.allowed_tools
    assert case.expected_state["primary_store_id"] == "store_people"
    assert case.timeout_seconds > 0
~~~

- [ ] **Step 2: Run and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_case_schema.py -q

Expected: FAIL because models, loader and case files do not exist.

- [ ] **Step 3: Implement versioned YAML loading**

cases.py 使用 Pydantic 校验 case_id、goal、allowed_tools、expected_state、forbidden_effects、timeout_seconds、max_tool_calls；拒绝未知工具、空目标、负数超时和重复 case_id。YAML 中的业务说明使用中文，标识和工具名保留英文。

- [ ] **Step 4: Add the first two read cases**

READ_PRIMARY_STORE 固定两店归属和主店；READ_NOT_IN_STORE 固定主部门在总部时 primary_store_id 为空、primary_store_status 为 not_in_store。用例不把部门数组顺序当成主部门依据。

- [ ] **Step 5: Run schema tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_case_schema.py -q

Expected: PASS。

### Task 2: 实现 Fake Feishu 和测试数据库夹具

**Files:**
- Create: backend/app/evaluation/fake_feishu.py
- Create: backend/app/evaluation/fixtures.py
- Create: backend/tests/evaluation/test_fake_feishu.py
- Modify: backend/tests/integration/conftest.py

**Interfaces:**
- Consumes: Collector 使用的 pages(resource, **params) 和 detail(kind, identifier) 接口。
- Produces:

~~~python
class FakeFeishu:
    def pages(self, resource: str, **params) -> Iterable[dict]: ...
    def detail(self, kind: str, identifier: str) -> dict: ...
    def emit(self, event_type: str, identifier: str) -> None: ...
    def set_scenario(self, name: str) -> None: ...

def reset_test_database(database_url: str) -> None: ...
def seed_case(factory, case: EvaluationCase) -> None: ...
~~~

- [ ] **Step 1: Write Fake Feishu tests**

覆盖多页分页、重复对象、乱序事件、父部门不可读、权限收窄、超时异常和 detail 来源 ID 校验；同一场景多次读取得到相同结果。

- [ ] **Step 2: Run and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_fake_feishu.py -q

Expected: FAIL because FakeFeishu and reset helpers are absent.

- [ ] **Step 3: Implement the adapter seam**

FakeFeishu 返回字段与现有 Collector.normalize_user、normalize_department 所需字段一致；scenario 由纯数据定义，不从 Worker 结果动态生成。权限收窄场景保留原对象历史事实，后续读取按场景返回不可读或缺失。

- [ ] **Step 4: Implement serial test reset**

reset_test_database 先校验 URL 数据库名以 _test 结尾，再按外键依赖顺序删除业务表数据，重新插入 dataset_state、task_queue_lock 和测试连接绑定；禁止在非测试库执行。每个 case 使用唯一 run_id，不并行共享数据库。

- [ ] **Step 5: Run fixture tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_fake_feishu.py -q

Expected: PASS；没有 ORG_TEST_DATABASE_URL 时只运行纯内存 Fake Feishu 测试。

### Task 3: 实现独立断言引擎

**Files:**
- Create: backend/app/evaluation/assertions.py
- Create: backend/tests/evaluation/test_assertions.py

**Interfaces:**
- Consumes: expected_state、forbidden_effects、独立读取服务、OperationReceipt、SyncJob、ChangeLog。
- Produces:

~~~python
class AssertionFailure(Exception):
    code: str
    message: str
    evidence: dict[str, Any]

def assert_case_postconditions(case, observation) -> list[AssertionFailure]: ...
def assert_forbidden_effects(case, observation) -> list[AssertionFailure]: ...
def assert_trace_policy(case, trace) -> list[AssertionFailure]: ...
~~~

- [ ] **Step 1: Write assertion tests**

覆盖主门店、not_in_store、门店投影、data_version、DATASET_CHANGED 后重读、pending_verification 保护、只读身份越权、审计缺失和秘密泄露。

- [ ] **Step 2: Run and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_assertions.py -q

Expected: FAIL because assertion functions do not exist.

- [ ] **Step 3: Implement independent data reads**

断言输入来自 test-only read connection 和能力观察接口；不调用 directory.domain.resolve_employee_stores、StoreAdminService._projection 或其他生产归属计算函数生成 expected_state。只比较固定 fixture、数据库事实、任务和日志。

- [ ] **Step 4: Implement hard gates**

硬失败包括越权、禁止副作用、错误终态、版本错误、事实不符、回执缺失、审计缺失、未知误报和敏感信息泄露。每个失败携带 code、message 和脱敏 evidence。

- [ ] **Step 5: Run assertion tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_assertions.py -q

Expected: PASS。

### Task 4: 实现 Worker Agent、Runner 和报告

**Files:**
- Create: backend/app/evaluation/worker.py
- Create: backend/app/evaluation/runner.py
- Create: backend/app/evaluation/report.py
- Create: backend/tests/evaluation/test_runner.py

**Interfaces:**
- Consumes: MCP client、EvaluationCase、Fake Feishu 和 assertion engine。
- Produces:

~~~python
class WorkerAgent(Protocol):
    def run(self, goal: str, mcp_client, context: AgentRunContext) -> AgentRun: ...

class ScriptedWorkerAgent:
    def run(self, goal: str, mcp_client, context: AgentRunContext) -> AgentRun: ...

class EvaluationRunner:
    def run_case(self, case: EvaluationCase) -> EvaluationReport: ...
    def run_suite(self, cases: Sequence[EvaluationCase]) -> list[EvaluationReport]: ...
~~~

- [ ] **Step 1: Write runner lifecycle tests**

验证生成唯一 run_id、reset/seed、启动 Fake Feishu 和 MCP client、达到终态后调用独立断言、超时生成 unconfirmed、无论成败都清理、报告不含 secret。

- [ ] **Step 2: Run and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_runner.py -q

Expected: FAIL because runner、worker protocol 和 report generator 不存在。

- [ ] **Step 3: Implement ScriptedWorkerAgent**

只用于 runner 单元测试和 MCP 契约验证；按预置步骤调用 MCP，不直接写数据库。步骤覆盖查询、预览、确认、apply、request_sync、poll get_sync_job 和最终读取。

- [ ] **Step 4: Implement provider-neutral WorkerAgent adapter**

adapter 接收 goal、MCP client 和 AgentRunContext，返回工具轨迹与最终文本；模型配置从环境变量读取，日志只记录模型别名和 token 使用摘要。真实模型适配在数据边界确认后启用。

- [ ] **Step 5: Implement runner and report**

Runner 限制工具调用次数、超时和终态；每次调用保存脱敏 ToolTraceEvent。report.py 输出 JSON 和中文 Markdown，包含 hard_passed、失败代码、证据、轨迹摘要和软评分。

- [ ] **Step 6: Run runner tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation/test_runner.py -q

Expected: PASS。

### Task 5: 加入六个用例和 CI CLI

**Files:**
- Create: backend/tests/evaluation/cases/ORG_AGENT_APPLY_STORE.yaml
- Create: backend/tests/evaluation/cases/ORG_AGENT_SYNC_SUBTREE.yaml
- Create: backend/tests/evaluation/cases/ORG_AGENT_VERSION_CONFLICT.yaml
- Create: backend/tests/evaluation/cases/ORG_AGENT_PERMISSION_SHRINK.yaml
- Create: backend/app/evaluation/cli.py
- Create: backend/tests/evaluation/test_agent_cases.py
- Create: deploy/tests/test_evaluation_runtime.py

**Interfaces:**
- Consumes: case loader、Fake Feishu、Runner、MCP client 和 assertions。
- Produces: python -m app.evaluation.cli --suite smoke 的稳定退出码。

- [ ] **Step 1: Add four case definitions**

APPLY_STORE 固定预览到应用的确认链；SYNC_SUBTREE 固定多页和任务状态；VERSION_CONFLICT 注入一次独立门店修改；PERMISSION_SHRINK 隐藏已有对象并期待 pending_verification。每个 forbidden_effects 写出具体 object_type、object_id 和禁止状态。

- [ ] **Step 2: Write CLI tests**

~~~python
def test_smoke_cli_returns_zero_when_hard_assertions_pass():
    assert run(["--suite", "smoke", "--case", "ORG_AGENT_READ_PRIMARY_STORE"]) == 0

def test_cli_rejects_non_test_database():
    assert run(["--suite", "smoke", "--database-url", "mysql+pymysql://x/y"]) == 2
~~~

- [ ] **Step 3: Implement CLI and exit codes**

退出码 0 表示硬断言全部通过；1 表示至少一个用例硬断言失败；2 表示配置、迁移或环境安全检查失败。CLI 默认串行执行，--case 选择单个用例，--output 指定脱敏报告目录。

- [ ] **Step 4: Run evaluation tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation -q

Expected: schema、Fake Feishu、断言、Runner 和用例测试 PASS；真实模型未配置时使用 ScriptedWorkerAgent。

- [ ] **Step 5: Run the MySQL smoke suite**

~~~powershell
docker compose -f deploy/compose.mysql-test.yaml up -d --wait
$env:ORG_TEST_DATABASE_URL = "mysql+pymysql://organization_test:local-integration-only@127.0.0.1:13306/organization_test?charset=utf8mb4"
Push-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.evaluation.cli --suite smoke --database-url $env:ORG_TEST_DATABASE_URL --output ..\artifacts\agent-evaluation
Pop-Location
~~~

Expected: exit 0；报告带 run_id、case_id、版本、任务和审计证据，且不含 secret。

- [ ] **Step 6: Add provider-neutral CI commands**

deploy/README.md 和 docs/运行与验收.md 记录提交级、MySQL 集成和 Agent smoke 命令；不添加平台专属 YAML。

### Task 6: 增加 LLM Judge 诊断和验收文档

**Files:**
- Create: backend/app/evaluation/judge.py
- Create: backend/tests/evaluation/test_judge.py
- Modify: backend/app/evaluation/report.py
- Modify: docs/运行与验收.md
- Modify: deploy/README.md
- Modify: README.md

**Interfaces:**
- Consumes: EvaluationReport、脱敏轨迹和 Worker 最终文本。
- Produces:

~~~python
class Judge(Protocol):
    def score(self, case: EvaluationCase, report: EvaluationReport, final_text: str) -> dict[str, float]: ...

class DeterministicJudge:
    def score(self, case, report, final_text) -> dict[str, float]: ...

class OptionalLlmJudge:
    def score(self, case, report, final_text) -> dict[str, float]: ...
~~~

- [ ] **Step 1: Write deterministic judge tests**

验证 hard_passed=false 时总分不能标为通过；缺少最终证据时 evidence_quality 降低；正确处理 unknown/pending 时 uncertainty_handling 提高；输出只包含分数和脱敏摘要。

- [ ] **Step 2: Implement deterministic scoring**

评分维度固定为 intent_understanding、tool_selection、evidence_quality、uncertainty_handling、efficiency，范围 0.0～1.0。硬门槛由 assertions 决定，不被软分数覆盖。

- [ ] **Step 3: Add optional LLM adapter**

只有显式配置模型和数据出境策略时启用；默认返回 disabled，不发送生产数据。请求内容使用脱敏 goal、工具摘要和 report evidence。

- [ ] **Step 4: Run judge and evaluation tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/evaluation -q

Expected: PASS；没有模型配置时 judge 不阻断，报告仍完整。

- [ ] **Step 5: Update acceptance records**

docs/运行与验收.md 增加六个 Agent Evaluation 用例、MySQL 命令、硬门槛和 LLM 诊断口径；README.md 说明真实 Agent、真实飞书和生产模型仍需独立验收。

- [ ] **Step 6: Commit the evaluation subsystem**

~~~powershell
git add backend/app/evaluation backend/tests/evaluation backend/tests/integration/conftest.py deploy/compose.mysql-test.yaml deploy/tests/test_evaluation_runtime.py docs/运行与验收.md deploy/README.md README.md
git commit -m "feat: add agent evaluation runner"
~~~

## Verification Checklist

- [ ] 用例 schema 拒绝未知工具、空目标和非正超时。
- [ ] Fake Feishu 覆盖分页、重复、乱序、权限收窄和不可读祖先。
- [ ] Worker Agent 没有 SQL、数据库和 Fake Feishu 访问能力。
- [ ] Evaluator 不调用生产归属计算函数生成 expected_state。
- [ ] 非 _test 数据库会让 CLI 退出 2。
- [ ] 六个用例重复运行时 hard_passed 结果稳定。
- [ ] 硬断言失败退出 1；LLM Judge 只记录诊断。
- [ ] 报告不包含密码、token、secret、CSRF、OAuth 或未授权员工字段。
- [ ] 真实飞书不进入普通 CI。

