# MCP Adapter and Policy Implementation Plan

**For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans。按任务实施；用复选框跟踪完成情况。

**Goal:** 将能力层以独立 MCP 适配服务暴露给生产人工 Agent 和隔离 CI Worker，并落实工具 schema、身份、分级权限、确认和调用追踪。

**Architecture:** MCP 适配层不实现组织业务逻辑，通过受保护的内部能力 HTTP 边界调用 OrganizationCapabilities。生产和测试使用同一工具名称与结果结构，只切换 base URL、Agent 身份、环境和策略；MCP 适配层不直接访问数据库。

**Tech Stack:** Python 3.11+、官方 Python MCP SDK、Pydantic、httpx、pytest、Docker Compose。

**Spec:** docs/architecture/agent-native-requirements-clarification.md

## Global Constraints

- 必须先完成 2026-10-13-capability-observation-layer.md 的 Task 5。
- MCP 工具不导入 SQLAlchemy Model，不创建数据库 Session，不绕过能力层。
- 工具名称、参数和结构化结果与 Capability Contract 一致。
- 生产人工 Agent 的 L2 能力需要人工确认；CI Worker 只在 test 环境自动确认。
- 日志和工具结果不得泄露 token、secret、密码或未授权敏感字段。
- 当前未指定 CI 平台；本计划提供可被任意 CI 调用的 Python 入口。
- 默认使用独立 sidecar 的 Streamable HTTP；若最终采用 stdio，只增加 transport adapter，不改变工具和策略层。

---

## 范围与文件地图

### 新建文件

- backend/app/mcp/__init__.py
- backend/app/mcp/models.py
- backend/app/mcp/auth.py
- backend/app/mcp/policy.py
- backend/app/mcp/client.py
- backend/app/mcp/trace.py
- backend/app/mcp/server.py
- backend/app/mcp/__main__.py
- backend/tests/test_mcp_contract.py
- backend/tests/test_mcp_auth.py
- backend/tests/test_mcp_policy.py
- backend/tests/test_mcp_tools.py
- deploy/tests/test_mcp_runtime.py

### 修改文件

- backend/pyproject.toml、backend/requirements.lock：加入并固定官方 MCP SDK。
- backend/app/config.py：MCP listen、能力服务 URL、service token、Agent identity 和 environment。
- compose.yaml、Dockerfile：增加 sidecar 启动和健康检查。
- .env.example、deploy/README.md、docs/backend-api.md：增加配置和运行边界说明。

## 固定工具目录

### L0 查询与观察

get_system_status、find_departments、get_department、list_employees、get_employee、list_stores、get_store、list_store_employees、get_change_logs、get_sync_job。

### L1 预览

preview_store_changes。

### L2 受控写入

apply_store_changes、request_sync、retry_sync_job。

### L3 禁止

飞书组织写入、员工写入、任意 SQL、管理员白名单、API 凭据、覆盖验收和系统配置工具。

## 固定模型

~~~python
class AgentPrincipal(BaseModel):
    actor_type: Literal["human_agent", "ci_agent"]
    actor_id: str
    environment: Literal["production", "test"]
    run_id: str | None = None
    case_id: str | None = None

class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool
    confirmation_required: bool = False
    fields: list[dict[str, Any]] = Field(default_factory=list)

class ToolResult(BaseModel):
    operation_id: str | None
    data: Any
    observation: dict[str, Any]
    audit: dict[str, Any]
    error: ToolError | None = None
~~~

### Task 1: 确认 SDK 与传输边界

**Files:**
- Modify: backend/pyproject.toml
- Modify: backend/requirements.lock
- Create: backend/app/mcp/__init__.py
- Create: backend/app/mcp/__main__.py
- Create: backend/tests/test_mcp_contract.py

**Interfaces:**
- Consumes: 能力层内部 HTTP router。
- Produces: server factory、固定 SDK 版本和 sidecar 启动入口。

- [ ] **Step 1: Verify official SDK compatibility**

阅读官方 Python MCP SDK 发布说明，选择支持 Python 3.11+、Streamable HTTP、工具 schema 和结构化结果的版本；把解析出的精确版本写入 pyproject.toml 和 requirements.lock，禁止使用未锁定范围版本。

- [ ] **Step 2: Write the failing handshake test**

~~~python
def test_mcp_server_factory_exposes_fixed_tool_names():
    server = build_server(test_dependencies())
    assert set(server.tool_names()) == {
        "get_system_status", "find_departments", "get_department",
        "list_employees", "get_employee", "list_stores", "get_store",
        "list_store_employees", "get_change_logs", "get_sync_job",
        "preview_store_changes", "apply_store_changes",
        "request_sync", "retry_sync_job",
    }
~~~

- [ ] **Step 3: Run and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_contract.py -q

Expected: FAIL because the MCP package and server factory do not exist.

- [ ] **Step 4: Add package entry points**

server.py 导出 build_server(client, policy, tracer)；__main__.py 支持 --transport streamable-http、--host、--port；入口只创建 MCP server 和内部 HTTP client，不创建组织数据库 Session。

- [ ] **Step 5: Run handshake tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_contract.py -q

Expected: PASS。

### Task 2: 实现身份、策略和脱敏追踪

**Files:**
- Create: backend/app/mcp/models.py
- Create: backend/app/mcp/auth.py
- Create: backend/app/mcp/policy.py
- Create: backend/app/mcp/trace.py
- Create: backend/tests/test_mcp_auth.py
- Create: backend/tests/test_mcp_policy.py

**Interfaces:**
- Consumes: AgentPrincipal、CapabilityResult 和内部服务 token。
- Produces:

~~~python
class PolicyDecision(NamedTuple):
    allowed: bool
    confirmation_required: bool
    code: str | None
    message: str | None

def decide(principal: AgentPrincipal, capability: str, approved: bool) -> PolicyDecision: ...
def redact_trace(value: Any) -> Any: ...
def verify_service_token(value: str, expected: SecretStr) -> bool: ...
~~~

- [ ] **Step 1: Write policy tests**

覆盖 production human_agent 的 L0/L1 自动允许、production human_agent 的 L2 未确认、production ci_agent 写入拒绝、test ci_agent 的 L2 自动允许、所有身份的 L3 禁止，以及 actor_id、run_id、case_id 进入 trace。

- [ ] **Step 2: Run focused tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_auth.py backend/tests/test_mcp_policy.py -q

Expected: FAIL because auth and policy modules are absent.

- [ ] **Step 3: Implement fail-closed authentication**

使用 hmac.compare_digest 比较 service token；缺 token、空 actor_id、环境与配置不匹配、production 使用 test run_id 时拒绝。异常信息和 trace 不输出 token。

- [ ] **Step 4: Implement the policy matrix**

将工具目录映射到 L0～L3；policy 只返回 decision，不执行业务。模型参数中的 approval_token 不自动视为确认。

- [ ] **Step 5: Implement trace redaction**

trace 保留 tool_name、actor_id、environment、run_id、case_id、operation_id、时间和 code；key 名含 secret、token、password、csrf、authorization 的值统一替换为 [REDACTED]。

- [ ] **Step 6: Run security tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_auth.py backend/tests/test_mcp_policy.py -q

Expected: PASS，且测试 secret 不出现在 repr、日志和 ToolResult。

### Task 3: 实现内部能力 HTTP client

**Files:**
- Create: backend/app/mcp/client.py
- Create: backend/tests/test_mcp_tools.py

**Interfaces:**
- Consumes: 内部能力 router 的 JSON envelope。
- Produces:

~~~python
class CapabilityHttpClient:
    async def call(self, path: str, payload: dict | None, principal: AgentPrincipal) -> ToolResult: ...
    async def read(self, path: str, params: dict, principal: AgentPrincipal) -> ToolResult: ...
~~~

- [ ] **Step 1: Write HTTP client tests**

使用 httpx.MockTransport 验证服务 token、actor headers、environment、4xx code、5xx retryable、UPSTREAM_TIMEOUT 和秘密字段过滤。

- [ ] **Step 2: Run and verify failure**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_tools.py -q

Expected: FAIL because CapabilityHttpClient is absent.

- [ ] **Step 3: Implement timeout and error mapping**

使用显式连接和读取超时；GET 查询不自动重试写操作；只有内部服务声明 retryable=true 的失败才返回可重试错误；客户端不自行重建 job 或修改 data_version。

- [ ] **Step 4: Run client tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_tools.py -q

Expected: PASS。

### Task 4: 注册 MCP 工具

**Files:**
- Modify: backend/app/mcp/server.py
- Modify: backend/app/mcp/models.py
- Modify: backend/tests/test_mcp_contract.py
- Modify: backend/tests/test_mcp_tools.py

**Interfaces:**
- Consumes: CapabilityHttpClient、policy、trace。
- Produces: 14 个固定工具，参数 schema 与能力层一致，返回 ToolResult。

- [ ] **Step 1: Add schema tests**

每个工具声明必填参数、最大长度、枚举范围和是否需要 data_version；find_departments 的 limit 最大 100，store changes 最大 500，sync type 只允许 initialize、reconcile、full、subtree。

- [ ] **Step 2: Register read tools**

查询工具只调用 client.read；get_sync_job 返回任务和观察结果，不把 succeeded 直接转为 verified。

- [ ] **Step 3: Register preview and writes**

preview_store_changes 只调用预览接口；apply_store_changes、request_sync、retry_sync_job 先通过 policy，再调用能力层。production L2 未确认时不发出写请求。

- [ ] **Step 4: Add ambiguity and version errors**

find_departments 返回多个候选时不选择；写操作缺 expected_version 或 idempotency_key 时在 MCP 层拒绝；内部 409 保留为 DATASET_CHANGED 或 OPERATION_CONFLICT。

- [ ] **Step 5: Run tool tests**

Run: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_mcp_contract.py backend/tests/test_mcp_tools.py -q

Expected: PASS。

### Task 5: 接入 Compose sidecar 和运行文档

**Files:**
- Modify: compose.yaml
- Modify: Dockerfile
- Modify: .env.example
- Modify: deploy/README.md
- Create: deploy/tests/test_mcp_runtime.py

**Interfaces:**
- Consumes: mcp.__main__ 启动入口和内部能力服务 token。
- Produces: 默认仅加入 Compose 内部网络的 mcp service。

- [ ] **Step 1: Write runtime tests**

验证 mcp service 使用独立 command、依赖 app health、没有 MySQL 端口暴露、没有把 token 放入镜像、健康检查失败时返回非零。

- [ ] **Step 2: Add configuration names**

.env.example 增加 ORG_MCP_HOST、ORG_MCP_PORT、ORG_CAPABILITY_BASE_URL、ORG_AGENT_SERVICE_TOKEN、ORG_AGENT_ID、ORG_AGENT_ENVIRONMENT；值保持空或示例占位。

- [ ] **Step 3: Add Compose service**

mcp 使用现有 Python 镜像，command 为 python -m app.mcp --transport streamable-http；只加入 app 和默认内部网络；默认不映射公网地址。

- [ ] **Step 4: Run runtime checks**

Run: backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_mcp_runtime.py -q

Expected: PASS；Compose YAML 能解析，服务依赖和变量名称正确。

- [ ] **Step 5: Update runbook**

deploy/README.md 说明启动顺序、token 注入、网络隔离、人工确认和 CI test environment 的差异；不写入 token 值。

- [ ] **Step 6: Commit the MCP subsystem**

~~~powershell
git add backend/app/mcp backend/pyproject.toml backend/requirements.lock backend/app/config.py backend/tests/test_mcp_*.py compose.yaml Dockerfile .env.example deploy/tests/test_mcp_runtime.py deploy/README.md docs/backend-api.md
git commit -m "feat: add guarded MCP adapter"
~~~

## Verification Checklist

- [ ] MCP handshake 和 14 个工具名稳定。
- [ ] production ci_agent 无法调用 L2。
- [ ] production human_agent 未确认时不产生内部写请求。
- [ ] test ci_agent 只能调用 test capability base URL。
- [ ] MCP 不创建数据库 Session，不导入 ORM Model。
- [ ] timeout 不自动重复写入。
- [ ] trace 不包含 token、密码、CSRF 或 OAuth 原文。
- [ ] sidecar 默认不暴露公网端口。

