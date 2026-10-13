# 组织架构系统 Agent Native 能力与 MCP 评估架构归档

| 项目 | 内容 |
|---|---|
| 文档状态 | 需求澄清已完成；分段设计已确认；整体设计已批准；实施计划阶段 |
| 最后更新 | 2026-10-13 |
| 适用范围 | 飞书组织架构维护系统的 Agent 能力、MCP 适配、观察层、Evaluation 与 CI |
| 当前基线 | 提交 b96d0d4：Harden sync initialization and runtime recovery |
| 实施状态 | 尚未实施；本归档不包含代码、数据库迁移或部署配置 |

## 1. 结论摘要

1. 首期 Agent 只操作当前系统已有的查询、门店维护和同步能力，不直接创建、移动或删除飞书组织事实。
2. 采用“业务能力层 + 独立 MCP 适配层”；MCP 不直接访问数据库，也不复制业务逻辑。
3. 人工对话和 CI 共用同一套 MCP 工具契约，但生产人工 Agent 与 CI Worker 使用不同身份和环境。
4. 生产人工 Agent 可以执行受控写操作；CI Worker 只连接隔离的 MySQL 测试库、Fake Feishu 和测试 MCP 身份。
5. 观察层必须分别表达请求记录、任务执行、业务提交、事实质量和最终验证，不能把 HTTP 成功或任务 succeeded 直接解释为业务完成。
6. Evaluator 以数据库、观察接口、任务终态和审计记录等确定性断言为最终依据，LLM Judge 只辅助评价意图理解和过程质量。
7. 首批 Evaluation 从现有 AC01～AC32 场景中选择六类高风险用例，优先覆盖门店归属、异步同步、版本冲突、权限收窄和安全边界。
8. 当前设计已完成需求澄清和分段讨论，并已获批准进入实施计划阶段；代码工作尚未开始。

## 2. 业务目标与系统边界

### 2.1 业务目标

让组织架构维护系统可以被人和 Agent 共同使用，并且能被 Agent 自动验证：

- 查询组织、员工、门店、主门店和归属依据；
- 维护本地门店标记、编码和备注；
- 发起、观察和重试组织同步；
- 在数据版本、覆盖状态和同步质量不完整时如实表达不确定性；
- 通过独立 Evaluator 判断系统是否真正达到业务预期。

### 2.2 数据权威边界

| 数据 | 权威来源 | 当前系统操作 |
|---|---|---|
| 部门名称、上级、员工资料、部门关系、主部门、来源状态 | 飞书 | 同步、计算、只读展示 |
| 是否门店、门店编码、门店备注 | 本系统 | 管理员或受控 Agent 维护 |
| 部门路径、所属门店、主门店、有效状态、数据版本 | 系统计算 | 根据已提交事实重新计算 |
| 资产、薪资及其他下游业务关系 | 对应业务系统 | 本系统不保存、不审批、不修改 |

### 2.3 不在本归档范围内

- MCP 直接写回飞书部门或员工；
- 创建、移动、删除飞书部门；
- 新增或修改飞书员工；
- 任意 SQL、数据库管理和迁移执行工具；
- 管理员白名单、API 凭据和覆盖验收等运维级工具；
- 生产数据直接用于普通 CI；
- 用 LLM Judge 单独决定业务是否成功；
- 高可用集群、消息中间件和多租户能力。

## 3. 当前链路与方案插入点

### 3.1 当前系统链路

当前系统的主要业务链路是：

~~~text
管理员
  -> React / Ant Design 管理页面
  -> FastAPI 管理接口
  -> ReadService、StoreAdminService、同步任务服务
  -> MySQL

飞书通讯录与事件
  -> Feishu listener / client
  -> Collector 采集与规范化
  -> Worker 领取任务
  -> Publisher 原子发布
  -> MySQL 中的部门、员工、门店投影、任务、事件和变更日志

其他业务系统
  -> 只读 HTTP API
  -> 版本一致的组织、员工和门店数据
~~~

现有实现已经包含数据世代、数据版本、分页游标、同步任务、事件收件箱、待核实事实和变更日志。真实 MySQL 并发、真实飞书权限和事件仍按运行验收台账待联调。

### 3.2 目标链路

~~~mermaid
flowchart LR
    U[人工用户] --> WA[生产 Worker Agent]
    C[CI 用例] --> WT[测试 Worker Agent]
    WA --> MP[独立 MCP 适配层]
    WT --> MT[测试 MCP 适配层]
    MP --> CAP[业务能力层]
    MT --> TCAP[测试应用能力层]
    CAP --> DB[(生产 MySQL)]
    TCAP --> TDB[(隔离 MySQL 测试库)]
    CAP --> FS[真实飞书只读同步]
    TCAP --> FFS[Fake Feishu]
    EV[独立 Evaluator] --> OBS[观察接口 / 测试数据库]
    OBS --> TDB
    EV --> REP[确定性断言与评估报告]
~~~

MCP 负责协议、工具发现、身份、权限、确认和调用追踪；能力层负责业务语义、事务、版本校验和审计；Evaluator 不采信 Worker 的自报结果。

## 4. 术语与状态边界

| 术语 | 定义 |
|---|---|
| 能力层 | 面向业务动作的稳定接口，封装查询、门店修改、同步任务和观察结果 |
| MCP 适配层 | 将能力层暴露为 MCP 工具，并处理 Agent 身份、权限、确认和调用追踪 |
| Worker Agent | 接收用户目标、通过 MCP 调用系统能力的 Agent |
| Evaluator | 独立读取系统事实并判断用例是否满足预期的评估组件 |
| Observation | 描述请求、任务、业务事实、质量和审计证据的观察结果 |
| 操作回执 | 关联操作 ID、调用身份、任务、提交版本和审计记录的持久结果 |
| 数据世代 | dataset_epoch；恢复或重新初始化后变化，用于识别数据来源世代 |
| 数据版本 | data_version；同一数据世代内的内容版本，用于一致读和 409 冲突 |
| 待核实 | 已有事实保留，但当前采集证据不足以确认其最新状态 |
| 已验证 | Evaluator 根据独立证据确认用例的业务后置条件已满足，不等于 SyncJob 的数据库状态 |

### 4.1 业务成功的层级

以下是观察层建议使用的状态名。它们不替换现有 SyncJob 的 queued、running、succeeded、failed，而是描述 Agent 操作从请求到独立验证的更完整阶段。

| 状态 | 代表含义 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| request_recorded | 操作回执已提交 | 系统记住了请求 | 任务已被 Worker 执行 |
| accepted | 返回 job_id，任务 queued 或复用 | 调度器接受了任务 | 外部同步已成功 |
| running | Worker 已领取并更新阶段 | 正在处理 | 业务事实已提交 |
| submitted | 发布事务完成，SyncJob 为 succeeded | 本轮发布事务已结束 | 所有对象都已核实或满足用例 |
| verified | 独立观察满足用例断言 | 业务后置条件成立 | 未来不会再次变化 |
| partial | 任务提交，但存在待核实事实 | 已知部分结果和质量 | 不可核实对象的真实状态 |
| failed | 任务或操作进入失败终态 | 本轮未达到提交或验证条件 | 失败一定可以安全重试 |
| unconfirmed | 超时、连接中断或证据不足 | 当前不能下结论 | 任务失败或业务删除 |

## 5. 已确认结论、当前建议和待确认事项

### 5.1 已确认结论

| 主题 | 已确认内容 |
|---|---|
| Agent 范围 | 只读 + 门店操作 + 同步操作 |
| 运行形态 | 人工对话和 CI 都支持 |
| 写操作 | 分级控制 |
| CI 权限 | 人工可写生产；CI 只写隔离环境 |
| Evaluator | 确定性断言为主，LLM 辅助 |
| 测试环境 | MySQL 测试库 + Fake Feishu |
| 架构 | 能力层 + 独立 MCP 适配层 |
| 当前阶段 | 先形成详细设计，再进入实现 |

### 5.2 当前建议

以下内容是设计建议，不应视为已经实施：

- 生产 MCP 以独立 sidecar 或独立服务运行，CI 以独立测试服务运行；
- 使用操作 ID和幂等键连接一次 Agent 操作的所有任务、版本和审计记录；
- 用例期望结果由固定夹具和独立断言定义，不复用生产归属计算函数生成答案；
- LLM Judge 初期只记录诊断分数，不作为发布阻断条件；
- 生产 rollout 按“只读观察 → 预览 → 确认后写入 → 范围受限同步”逐级开放。

### 5.3 待确认事项

| 项目 | 当前建议 | 影响 |
|---|---|---|
| MCP 部署形态 | 先用独立 sidecar / 服务 | 决定网络、凭据和发布方式 |
| 生产模型与数据边界 | 只允许经批准的模型或本地模型访问真实组织数据 | 决定隐私、网络和日志策略 |
| 确认入口 | 优先由 MCP 客户端承担人工确认 | 决定确认回执和 UI 工作量 |
| 操作回执结构 | 新增逻辑回执或扩展现有任务/日志 | 可能涉及数据库迁移 |
| 用例描述格式 | 以版本化 Markdown/YAML 作为测试资产 | 决定 CI 维护方式 |
| LLM 评分阈值 | 初期只做趋势指标 | 避免模型波动阻断发布 |
| 真实环境验收时间 | 待提供真实 MySQL 和飞书环境后安排 | 决定生产 rollout 节奏 |

## 6. 首期 Capability Contract

### 6.1 查询与观察能力

| 能力 | 业务用途 | 关键结果 |
|---|---|---|
| get_system_status | 查看初始化、覆盖、连接和版本 | 状态、质量、世代、版本、最近全量时间 |
| find_departments | 按名称、路径或稳定 ID 定位部门 | 候选列表；名称不唯一时不猜选 |
| get_department | 查看部门事实和门店资料 | 路径、来源状态、门店标记、质量 |
| list_employees / get_employee | 查看员工和部门关系 | 主部门、全部门店、主门店、路径和质量 |
| list_stores / get_store | 查看有效或历史门店 | 编码、备注、人数、主门店人数 |
| list_store_employees | 查看门店员工 | 全部归属或主门店归属 |
| get_change_logs | 查询对象、任务或操作者变更 | 前后差异、来源、审计时间 |
| get_sync_job | 观察任务执行和对象明细 | 阶段、终态、失败对象、错误码 |

### 6.2 受控写能力

| 能力 | 作用 | 生产策略 | CI 策略 |
|---|---|---|---|
| preview_store_changes | 校验门店修改并计算影响范围 | 自动 | 自动 |
| apply_store_changes | 应用门店标记、编码和备注 | 人工确认 | 测试身份自动 |
| request_sync | 提交初始化、全量、子树或核对任务 | 按范围确认 | 测试身份自动 |
| retry_sync_job | 重试符合条件的失败任务 | 受控 | 自动 |

所有写能力都必须使用系统生成的操作者身份，不能接受模型自行传入的 actor、权限或审计字段。

### 6.3 权限等级

| 等级 | 能力 | 生产人工 Agent | CI Worker |
|---|---|---|---|
| L0 | 查询、观察、日志读取 | 自动 | 自动 |
| L1 | 预览、影响分析 | 自动 | 自动 |
| L2 | 门店资料应用、范围受限同步 | 用户确认 | 隔离环境自动 |
| L3 | 凭据、管理员、覆盖验收、任意组织写入 | 禁止 | 禁止 |

## 7. 观察层设计

### 7.1 观察结果组成

观察结果应包含以下部分：

| 部分 | 内容 |
|---|---|
| execution | 请求记录、任务接收、执行中、已提交、失败、未确认 |
| fact_quality | 已核实、部分待核实、未知、不一致、失效 |
| operation | operation_id、capability、actor、run_id、case_id |
| job | job_id、任务类型、范围、阶段、终态、进度和错误 |
| dataset | dataset_epoch、data_version、coverage_status |
| evidence | 目标对象、影响对象、change_log_id、提交时间和后置条件 |
| next_action | 继续观察、重新读取、人工确认、重试或等待外部修复 |

### 7.2 关键规则

1. SyncJob 为 succeeded 只能表示发布事务结束，不能单独证明所有对象已核实。
2. 本轮无业务变化时 data_version 可以不增加，但观察结果仍应表明已完成核对。
3. 版本变化返回 DATASET_CHANGED；Agent 必须重新获取基准版本。
4. 等待超时返回未确认，不能自动补发同一写操作。
5. pending_verification、unknown、inconsistent 不能被解释为删除或离职。
6. 主部门不在门店下的 not_in_store 与主部门不可读的 unknown 必须区分。
7. 观察接口不返回 secret、token、密码或原始敏感载荷。

### 7.3 操作状态图

以下是建议的观察层状态，不替换当前 SyncJob 的 queued、running、succeeded、failed 数据库状态：

~~~mermaid
stateDiagram-v2
    [*] --> request_recorded
    request_recorded --> accepted: 返回 operation_id / job_id
    accepted --> running: Worker 领取
    accepted --> unconfirmed: 等待超时
    running --> submitted: 发布事务完成
    running --> failed: 终态失败
    running --> unconfirmed: 连接或观察超时
    submitted --> verified: 独立后置条件满足
    submitted --> partial: 存在待核实事实
    submitted --> unconfirmed: 无法取得完整观察
    failed --> accepted: 合法重试或复用
    partial --> verified: 后续核对补齐
    partial --> unconfirmed: 后续核对仍不可用
~~~

## 8. 场景矩阵

| 操作 | 输入或当前状态 | 处理方式 | 是否产生新业务变化 | 结果口径 |
|---|---|---|---|---|
| 查询员工主门店 | 主部门明确且祖先可读 | 读取同一版本的员工、部门和门店 | 否 | 返回 resolved 或 not_in_store |
| 查询员工主门店 | 主部门缺失、矛盾或祖先不可读 | 保留已知事实，返回质量和原因 | 否 | 返回 unknown 或 inconsistent |
| 预览门店修改 | data_version 匹配 | 校验字段、编码和影响人员 | 否 | 返回规范化修改和影响数量 |
| 应用门店修改 | data_version 匹配且已确认 | 锁定版本、提交资料、重建投影、写审计 | 可能 | 返回提交版本和审计证据 |
| 应用门店修改 | data_version 已变化 | 拒绝提交并要求重新读取 | 否 | 409 DATASET_CHANGED |
| 发起同步 | 相同范围任务正在运行 | 复用活动 job_id | 否 | 返回 reused=true |
| 发起同步 | 无活动同范围任务 | 创建 queued 任务 | 尚未 | 只能报告任务已接收 |
| 同步发布 | 某些对象不可读 | 保留旧事实，写 pending_fact，降低质量 | 可能 | 任务可结束但事实为 partial |
| 同步失败 | 可重试错误 | 按退避策略重试或人工重试 | 否 | failed，可继续观察 |
| 迟到或重复事件 | 当前事实已更新 | 按来源 ID 回查当前详情并去重 | 视事实而定 | 旧载荷不能覆盖新状态 |
| 只读身份调用写工具 | 机器凭据无写权限 | 拒绝并审计 | 否 | UNAUTHORIZED 或权限错误 |
| Worker 报告完成 | Evaluator 观察不满足 | 以独立证据为准 | 否 | 用例失败，保留完整轨迹 |

## 9. 组件时序

~~~mermaid
sequenceDiagram
    participant R as 用户或 CI 用例
    participant W as Worker Agent
    participant M as MCP 适配层
    participant K as Capability 层
    participant D as MySQL
    participant S as Sync Worker
    participant F as 飞书或 Fake Feishu
    participant E as 独立 Evaluator

    R->>W: 提供自然语言目标
    W->>M: 调用查询、预览或写工具
    M->>K: 校验身份、权限、确认和参数
    K->>D: 在事务中读取或提交
    D-->>K: 返回回执、版本和审计
    K-->>M: 返回结构化结果
    M-->>W: 返回工具结果

    W->>M: 请求同步任务
    M->>K: 创建或复用操作回执
    K->>D: 写入 queued 任务
    D-->>K: 返回 operation_id / job_id
    K-->>M: 返回已接收
    S->>D: 领取任务并更新阶段
    S->>F: 分页、详情回查或事件处理
    F-->>S: 当前事实或可控失败
    S->>D: 原子发布、投影、日志和质量

    E->>D: 独立读取任务、事实、版本和审计
    E->>E: 执行确定性断言
    E-->>R: 输出带证据的评估结果
~~~

## 10. Evaluation 用例与判定

### 10.1 用例逻辑结构

每个用例至少定义：

| 项目 | 内容 |
|---|---|
| case_id | 稳定的用例标识 |
| goal | 用户自然语言目标 |
| fixture | 初始 MySQL 数据和 Fake Feishu 场景 |
| allowed_tools | Worker 可用工具和权限等级 |
| expected_state | 目标对象、关系、质量和版本条件 |
| forbidden_effects | 禁止的对象变化和越权行为 |
| timeout_policy | 任务等待、轮询和重试上限 |
| cleanup | 用例结束后的数据库和 Fake Feishu 清理 |
| scoring | 硬门槛和软评分规则 |

Worker 不应看到 expected_state 或 forbidden_effects。Evaluator 可以读取用例期望和独立系统事实，但不使用 Worker 的自报结论生成期望值。

### 10.2 首批用例

| 用例 | 主要来源 | 硬断言 |
|---|---|---|
| 主门店解释 | AC08、AC09、AC11 | 主部门、多门店、not_in_store、unknown 和 inconsistent 不混淆 |
| 标记部门为门店 | AC07、AC13 | 预览、确认、投影、版本和日志一致 |
| 子树同步 | AC16、AC20 | 范围完整、任务终态正确、重复事件不覆盖新事实 |
| 版本冲突恢复 | AC26 | 409 后重新读取，不覆盖新版本 |
| 权限收窄保护 | AC18、AC30 | 不把不可见对象误判为删除或离职 |
| Agent 权限边界 | AC24、AC28 | 只读身份不能写入，secret 不进入日志或结果 |

### 10.3 评分规则

硬门槛失败时用例失败：

- 越权；
- 禁止副作用；
- 数据事实不符；
- 任务终态错误；
- 事务、版本或幂等错误；
- 审计或观察证据缺失；
- 把未知、待核实或超时误报成成功。

LLM Judge 仅评价意图理解、工具选择、效率、歧义处理和解释质量。初期其分数不直接阻断 CI。

## 11. 数据结构与约束

### 11.1 现有结构的复用

| 现有对象 | 在 Agent 体系中的用途 |
|---|---|
| dataset_state | 数据世代、内容版本、初始化和覆盖状态 |
| sync_job | 异步同步任务、阶段、终态、重试和计数 |
| sync_job_detail | 对象级处理结果、错误和关联日志 |
| event_inbox | 外部事件去重、排队、失败和重试 |
| pending_fact | 不完整采集事实及待核实原因 |
| change_log | 事实、关系、门店和安全操作审计 |
| employee_store | 员工门店归属和主门店投影 |
| api_client / admin_session | 现有只读机器身份和管理员会话边界 |

### 11.2 建议的操作回执逻辑结构

以下是设计阶段的逻辑结构，不是迁移脚本：

| 字段 | 约束 / 索引 | 含义 |
|---|---|---|
| operation_id | 唯一 | 一次 Agent 能力调用的稳定标识 |
| idempotency_key | 按 actor、环境和能力唯一 | 防止重复提交产生重复业务操作 |
| capability | 索引 | 调用的能力名称 |
| actor_type / actor_id | 索引 | 人工 Agent 或 CI Agent 身份 |
| environment | 索引 | production 或 test |
| run_id / case_id | 索引 | Agent 运行和 Evaluation 用例 |
| request_hash | 非空 | 规范化请求内容摘要 |
| status | 索引 | 操作回执状态 |
| job_id | 可空索引 | 关联的同步任务 |
| before_epoch / before_version | 非空 | 请求开始时的数据版本 |
| committed_epoch / committed_version | 可空 | 业务提交后的数据版本 |
| result_summary | JSON 或文本 | 脱敏后的结构化结果摘要 |
| error_code | 可空索引 | 最近错误 |
| created_at / updated_at | 非空 | 回执生命周期时间 |

如果最终采用新增表，迁移时必须按项目数据库规则为每个字段添加准确中文备注，并提供执行前检查、执行后验证和失败恢复说明。当前归档不创建该表。

## 12. MCP 结果载荷示例

以下为建议形态，不代表当前 API 已实现：

### 12.1 同步请求已接收

~~~json
{
  "operation_id": "op_20261013_0001",
  "capability": "request_sync",
  "data": {
    "job_id": "job_abc",
    "type": "subtree",
    "root_department_id": "dep_shanghai",
    "status": "queued",
    "reused": false
  },
  "observation": {
    "execution": "accepted",
    "dataset_epoch": "epoch_a",
    "data_version": 42
  },
  "next_action": "通过 get_sync_job 观察终态"
}
~~~

### 12.2 门店修改已提交

~~~json
{
  "operation_id": "op_20261013_0002",
  "capability": "apply_store_changes",
  "data": {
    "changed_count": 1,
    "affected_employee_count": 28
  },
  "observation": {
    "execution": "submitted",
    "fact_quality": "resolved",
    "dataset_epoch": "epoch_a",
    "data_version": 43
  },
  "audit": {
    "change_log_ids": ["log_1001"]
  }
}
~~~

载荷不得包含数据库密码、飞书 token、API secret、完整 OAuth 信息或未授权的原始人员敏感字段。

## 13. 重试、幂等、锁与恢复

| 情况 | 处理 | 是否重新产生业务操作 |
|---|---|---|
| 同一范围已有活动同步任务 | 复用原 job_id 和操作关联 | 否 |
| 同一 idempotency_key 重复应用门店修改 | 返回原操作回执 | 否 |
| 预览后数据版本变化 | 返回 409，重新读取后再预览 | 否 |
| 写请求超时且结果未知 | 先按操作 ID查询，不直接重提 | 未确认 |
| 同步采集部分不可读 | 保留旧事实并标记待核实 | 可能有质量变化 |
| 可重试的 Worker 失败 | 按退避重试或人工重试 | 复用业务范围，避免旧结果覆盖 |
| Worker 租约过期 | 拒绝过期 Worker 发布，等待接管 | 否 |
| 审计或发布事务失败 | 事实、投影、日志和版本整体回滚 | 否 |
| CI 用例结束 | 销毁独立数据库/schema 和 Fake Feishu 场景 | 不影响其他用例 |

MCP 适配层不得通过重复发送写请求来解决未知状态；必须先观察已有回执、任务和版本。

## 14. 排障口径

| 观察结果 | 代表含义 | 下一步 |
|---|---|---|
| 没有 operation_id | 能力调用未形成持久回执 | 查 MCP 鉴权、参数和能力层入口 |
| 有回执但没有 job_id | 请求记录了，但未创建异步任务 | 查能力层事务和任务提交 |
| job queued 长时间不变 | 任务已接收但未被 Worker 领取 | 查 Worker、租约、数据库连接和任务锁 |
| job succeeded 且有 pending | 发布事务结束，但部分事实不可核实 | 查 pending_fact、权限和后续全量核对 |
| job failed 且可重试 | 本轮没有完成 | 查对象级错误和重试条件 |
| 409 DATASET_CHANGED | 观察或预览基准已过期 | 重新读取世代和版本 |
| primary_store_status unknown | 主部门或祖先不可读，不能判断 | 查覆盖状态和待核实对象 |
| Agent 声称完成但 Evaluator 失败 | Worker 结论与独立事实不一致 | 以 Evaluator 证据为准，保留工具轨迹 |
| MCP 返回未授权 | 身份或权限等级不允许 | 查 Agent principal、环境和确认策略 |
| 只读凭据调用写工具 | 权限边界生效 | 不降级为管理员身份，记录安全审计 |

## 15. 实施边界与阶段

| 阶段 | 主要工作 | 完成标准 |
|---|---|---|
| 0. 契约冻结 | 工具清单、权限、状态、错误码、回执和六个用例 | 每个能力有输入、输出、权限和成功条件 |
| 1. 能力与观察层 | 收敛现有查询、门店、同步和审计服务；补统一回执和观察结果 | 不经过 MCP 也能完成并验证一次业务操作 |
| 2. MCP 适配层 | 独立服务、schema、身份、确认和调用追踪 | MCP 契约、鉴权和错误映射通过 |
| 3. Evaluation Runner | 夹具、Fake Feishu、Worker 调度、轨迹和确定性断言 | 六个首批用例可在 MySQL 测试库重复运行 |
| 4. CI 门禁 | 快速测试、MySQL 集成、Agent Evaluation 和报告 | 确定性失败阻断，LLM 评分只诊断 |
| 5. 生产灰度 | 只读、预览、确认后写入、范围受限同步 | 每一步都有审计、观察和失败恢复路径 |
| 6. 真实环境验收 | MySQL、飞书权限、OAuth、事件、长连接和恢复 | 通过真实环境验收后才扩大权限 |

阶段 1 是阶段 2 的前置；阶段 3 可以在能力契约冻结后准备夹具，但 Worker 必须通过阶段 2 的 MCP 执行；阶段 4 依赖阶段 1～3；阶段 5 和 6 不属于当前已实施范围。

## 16. 与现有文档和 ADR 的关系

- 与 方案.md 的单企业、飞书唯一来源、本地门店字段和只读下游边界一致。
- 与 同步与接口设计.md 的数据世代、数据版本、待核实、同步任务和审计设计一致。
- 与 决策与验收.md 的 AC01～AC32 场景直接衔接，首批 Agent 用例从这些场景抽取。
- 与 docs/backend-api.md 的公共读取、管理写入、同步任务和错误码保持兼容；MCP 不应绕过这些业务语义。
- 与 ADR 0001 一致：本归档属于架构与需求文档，不改变产品版本；若后续实施改变产品行为，再按版本台账规则更新 CHANGELOG.md。
- 当前没有发现与现有 ADR 的直接冲突。若操作回执或 Agent 权限成为长期架构，应在整体设计批准后新增独立 ADR。

## 17. 后续行动与尚未实施

1. 进入实施计划阶段，拆分能力层、观察层、MCP、Evaluation 和 CI 任务。
2. 在实现前补齐操作回执和幂等的逻辑设计，以及首批用例的夹具定义。
3. 确认 MCP 部署位置、生产模型与真实数据边界、人工确认入口。
4. 提供隔离 MySQL 和 Fake Feishu 运行环境后，执行 MySQL 集成与 Agent Evaluation。
5. 真实飞书联调、生产 rollout 和权限扩大必须单独验收。

本文件只是需求和架构结论的归档，不表示 MCP、Agent、Evaluator 或新的操作回执已经上线。

