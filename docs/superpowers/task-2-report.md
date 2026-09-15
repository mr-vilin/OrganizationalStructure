# Task 2 实施报告

## 状态

飞书登录、候选采集、事件收件箱、原子发布、租约 worker、长连接入口与管理接口已实现。本轮未启动 Docker、未连接真实 MySQL 或真实飞书组织，不把离线通过等同于企业验收。

按 Superpowers TDD 先新增行为测试并观察失败，再实现并回归。包含分页中途失败、缺失/冲突主部门、关系字段缺失、乱序删除后恢复、不可读详情、旧子树对象移出、租约失效、投影祖先不可信、后代门店影响计数、原子事务回滚、无变化不加版本、OAuth state 重放及不同组织复用数据库等用例。

## 文件与行为

- `backend/app/feishu/client.py`：按本地官方 SDK 1.7.3 核验的 HTTP 契约调用 OIDC、user_info、通讯录 scope/children/users/detail。应用 token 与用户 token 分开，OIDC 使用 `data.access_token`；分页检测重复/缺失 token。错误仅输出固定脱敏代码。
- `backend/app/feishu/oauth.py`、`binding.py`：一次性持久 OAuth state、浏览器绑定、租户/白名单校验、同应用 open_id/user_id 映射、数据库 app/tenant 永久绑定约束。
- `backend/app/feishu/events.py`、`listener.py`、`health.py`：六类通讯录对象事件及 scope 更新事件的身份校验、持久去重、缺字段可见失败；独立 SDK 长连接进程只快速入箱。只使用公开重连 hooks，不使用 SDK 私有连接/停止字段。未知或过期连接证据一律 degraded。
- `backend/app/sync/collector.py`：完整分页候选、显式唯一主部门、祖先补齐、全量旧记录回查、旧子树对象移动回查、跨范围关系保留。详情不可读保留已有事实，仅降质量；成功且状态明确失效的详情才能改 inactive。
- `backend/app/sync/publisher.py`：全局租约与任务世代 fence、数据状态锁、暂存候选、事实/关系/门店投影/日志/版本/任务状态同事务。新旧合并部门树检查环路。无业务变化不增加版本。
- `backend/app/sync/worker.py`、`settings.py`：120 秒单 worker 租约、30 秒续期、过期任务恢复、失败指数退避最多五次、真实阶段/计数持久化、每日北京时间调度及启动全量核对。
- `backend/app/stores/service.py`、`directory/domain.py`：preview 基于实际前后投影对比，覆盖后代且排除嵌套门店未变化员工；保留不可信祖先/主部门状态，门店投影填充实际派生路径。
- `backend/app/main.py`、`admin/router.py`、`persistence/read_service.py`：OAuth/会话/退出接线，连接状态和覆盖验收摘要，调度设置，失败事件列表/重试，日志动作/操作人/UTC 时间筛选，员工部门和门店可解释路径，部门备注。
- `backend/app/persistence/models.py`、`migrations/versions/0002_feishu_runtime.py`：新增 `oauth_state/login_identity/worker_lease`，保留冻结 0001。`repositories.py` 的任务认领尊重退避截止时间。
- `backend/tests/test_feishu_*.py`、`test_sync_*.py`：本轮行为回归。SQLite 测试只用于业务事务验证，绝不替代真实 MySQL 锁语义验收。
- `docs/backend-api.md`：准确前后端契约。

## 验证

在 `backend` 工作目录执行：

```powershell
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m alembic upgrade head --sql
./.venv/Scripts/python.exe -m app.sync.worker
./.venv/Scripts/python.exe -m app.feishu.listener
```

- 全套：**57 passed、6 skipped、1 warning**。6 个跳过项因未提供独立 `ORG_TEST_DATABASE_URL`；其中恢复测试由根代理实现。唯一 warning 来自 Starlette/AnyIO 已有弃用别名。最后补充状态字段/父部门字段缺失保护，不把缺字段推断为活动或根部门。
- Alembic 离线 SQL 生成成功，包含冻结 0001 与新增 0002；无数据库执行。
- 未配置环境下 worker/listener 明确报告配置缺失并非零退出，不假装同步成功。
- 已把本地 `lark_oapi-1.7.3-py3-none-any.whl` 及依赖安装到项目 `.venv`。实际构建七类 SDK handler 与 `ws.Client`，公开 `on_reconnecting/on_reconnected` 均可调用；没有调用 `start()`。实际 SDK `P2ContactUserCreatedV3` → `JSON.marshal` 验证保留 `header.event_id/event.object.user_id`。

## 配置与运行

必需配置：`ORG_DATABASE_URL`（mysql+pymysql）、`ORG_SESSION_SECRET`、`ORG_FEISHU_APP_ID`、`ORG_FEISHU_APP_SECRET`、`ORG_FEISHU_TENANT_KEY`。HTTP 登录另需 `ORG_FEISHU_REDIRECT_URI` 指向 HTTPS `/admin/auth/callback`，以及首次初始化 `ORG_INITIAL_ADMIN_OPEN_IDS`。

可选声明/验收配置：

- `ORG_FEISHU_SCOPES`：逗号分隔的运维已申请权限名称，仅声明，不伪称平台验证结果。
- `ORG_COVERAGE_ACCEPTANCE_REFERENCE`：已发布应用版本与企业覆盖验收依据摘要/编号，默认空。
- `ORG_COVERAGE_ALL_MEMBERS_VERIFIED`、`ORG_COVERAGE_DEPARTMENTLESS_VERIFIED`：默认 false；两项与非空依据均满足后，采集器仍须完成根/各分页/祖先/详情验证才可能 complete。
- scope 更新事件使 `system_setting.coverage_invalidated` 持久生效并把覆盖降为 unknown；运维重新完成验收后清除此标记，再全量核对，不能靠前端全员开关解除。

迁移后由监督器运行三个独立进程：`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`、`python -m app.sync.worker`、`python -m app.feishu.listener`。HTTP 不执行远程同步，部署监督配置由根代理负责。

恢复环境必须让全部进程停止后处理：清空 OAuthState，WorkerLease 的 owner/expires_at 清空且 generation 递增；FeishuConnection 保留原绑定。根代理恢复 CLI 已接续这些字段。

## 明确限制与真实联调清单

- MySQL 行锁互斥、续租/失联接管、并发事件去重、发布/审计异常回滚与真实迁移仍需提供 MySQL 环境后验证。
- OIDC 的 tenant_key/user_id 实际权限、授权回调白名单、拒绝授权、无部门员工覆盖、scope 用户组入口、删除/离职字段和错误码，仍需企业联调。任何未知错误码都不会被猜成失效。
- 官方 scopes 无全员布尔值，当前没有经确认的独立全企业自然人枚举接口；默认 unknown，用户组未解析或详情不可读为 incomplete。不会把递归成功等同全企业人员完整。
- SDK 1.7.3 没有公开首连成功或停止 API；首次连接状态保持 degraded，接收合法事件或重连成功后短期 connected，无近期证据再 degraded。由监督器执行进程终止/重启；启动及重连全量核对弥补潜在遗漏。
- 采集失败任务自动退避重试；对象事件处理失败及不可确认失效通过事件列表显式暴露，管理员可重试。缺对象 ID 的事件需核查权限并全量核对，不能编造 ID 后重试。
- 候选采集在内存隔离完成，发布事务内写入/清理 staging 并原子提交；崩溃后整轮重采，不承诺逐页断点续传。

## 修复轮 1（独立审查后）

已修复 4 项 Important、安全错误码 Minor，以及根代理补充的数据库/框架错误 envelope。此节与更新后的 API/部署文档替代前文关于手工清除 coverage marker 的历史描述。

1. **覆盖可恢复**：新增 `app/sync/coverage.py` CLI，校验组织绑定，在同一事务保存真实验收 reference、清除失效 marker、写审计并新建 reconcile 任务。worker 每轮读取持久验收，HTTP 状态优先展示持久依据。覆盖只设 unknown；采集开始时间早于重新验收的旧候选也不能恢复 complete。完整命令见 `docs/backend-api.md`、`deploy/README.md`。新增验收审计故障注入，证明标记/依据/任务一起回滚。
2. **身份绑定不可覆盖**：OAuth 锁定已有 LoginIdentity 三元组，异常拒绝 `LOGIN_IDENTITY_MISMATCH`。在退出事务后抛拒绝异常，固定错误码安全事件已提交，原映射不变；不保存 code/token/secret。
3. **未知部门不再造事实**：新增 `PendingFact` 与 `0003_pending_fact`。未解析引用和候选单独保存，新依赖事实延后发布；已有事实/关系保留，仅降质量。后续全量会回查 pending ID，确认后发布并清理 pending；已有部门的新父级不可读时保留原父级与名称、主门店解析为 unknown。冻结 0001 未修改。
4. **确认离职撤权**：发布 inactive 员工时按 LoginIdentity 锁定管理员身份，在事实发布同事务撤销所有活动会话并审计；实时会话查询及新 OAuth 均拒绝明确 inactive。pending 不撤权，白名单保持原规则，最后管理员没有豁免。通过发布阶段故障注入验证事实/撤权/版本一起回滚。
5. **稳定故障反馈**：worker 使用固定安全错误码集合，关键字段缺失不会被折叠成通用 SYNC_FAILED。SQLAlchemy 数据库不可用异常返回 503 JSON，其他数据库异常返回 500 JSON；404/405 同样进入统一 error envelope。engine 使用 hide_parameters，处理器不记录/输出 SQL、参数或异常原文。

### 修复验证

在 backend 工作目录执行：

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_task2_review_fixes.py -q
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m alembic upgrade head --sql
./.venv/Scripts/python.exe -m app.sync.coverage --help
```

针对性首轮 RED：9 failed、1 passed（原有回滚保护）；实现后 10 passed，随后增加验收回滚、pending 重新解析、CLI 行为、旧采集覆盖保护和未知新父级用例。最终针对性 **16 passed**；全套 **73 passed、6 skipped、1 warning**。`alembic upgrade head --sql` 成功输出含 0003 的 MySQL DDL；coverage CLI `--help` 退出 0，CLI 实际参数解析/排队行为使用本地测试库故障隔离验证。真实 MySQL/飞书继续未执行。第三方 Starlette/AnyIO 弃用 warning 保留明确记录，没有升级整个框架或加入宽泛过滤。部署文档同步要求订阅第七类 `contact.scope.updated_v3`。

## 修复轮 2：确认离职不再依赖部门关系可读性

修复 AC25 接续缺口：`collector.normalize_user` 先验证稳定来源 ID 与显式布尔生命周期；active 且关系缺失仍只 pending，明确 inactive 则可以携带“关系未解析”候选，不再丢弃可信离职证据。Collector 在调用规范化前再次核对请求 user_id，防止错误响应误撤权。

`Publisher._defer_unresolved` 对明确 inactive 保留独立生命周期发布通道。已有员工仅更新状态与质量，保留最后已知姓名、来源 ID、主部门与历史关系；把当前关系置 inactive、重建后移除当前门店归属，并撤销关联管理员活动会话。新员工有已确认身份资料时保存 inactive，主部门暂为 null；未读部门仍不创建，新增关系及原候选继续保存到 PendingFact。资料、关系、审计、撤权及版本同事务提交。

新增 `tests/test_task2_inactive_relations.py`：首次 **5 failed、3 passed**，观察到已有离职事实被整体延后、新 inactive 员工缺失和撤权/关系日志未执行。修复后增加父部门字段缺失与实际关系写入故障注入。最终针对性 **10 passed**，覆盖关系/父字段不可读的明确离职、请求来源 ID 不符、生命周期缺失/非布尔不撤权、关系和安全审计失败回滚、新员工不生成假部门。

在 backend 目录执行：

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_task2_inactive_relations.py -q
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m alembic upgrade head --sql
```

最终全套 **83 passed、6 skipped、1 第三方弃用 warning**。离线迁移仍成功生成到 0003，本轮不新增 schema 变更。未连接真实 MySQL、飞书或其他外部环境；未改前端或派生代理。真实并发锁与企业生命周期语义继续保留未验收。

## 整体审查 F1 修复及日志分页契约修复

部门生命周期与不可读父引用解耦：规范化先校验请求来源 ID 和显式布尔 is_deleted；已有部门明确 inactive 时，即便新父引用缺失/不可读，保留历史名称及父引用、独立更新生命周期。未知新部门缺少父引用仍只进入 PendingFact，不编造根关系。全量遍历不再请求明确已删除部门的 children/users 接口。

Publisher 在同一事务结束已删除部门的直接当前 EmployeeDepartment，保留历史关系；员工本人、其他有效兼职与管理员会话不变。子部门不级联删除。员工后续详情即使仍含 inactive 部门也不会恢复其关系；必须先有明确部门恢复，再有可信员工关系回查。部门事实、关系、投影、日志与版本原子提交，重复无变化删除不加版本。

`directory/domain.py` 与 `stores/service.py` 的派生路径均在 inactive 节点停止。额外回归发现：当员工另外有同一上层门店的合法直接关系时，旧路径生成可能借用跨删除祖先的主部门路径；已修正，合法兼职路径仍仅来源于它自己的有效关系。

整体审查补充的日志分页也已修复：`GET /admin/api/change-logs` 的 `meta.next_cursor` 返回 string|null，查询仍接受数字文本。HTTP 行为测试通过真实路由和 SQLite 存储连续读取 205 条日志（100/100/5），验证游标类型、顺序、无重复和无遗漏。未改前端。

TDD 证据：部门生命周期首轮 **6 failed、3 passed**；修复后 9 passed。新增合法兼职路径回归观察到原错误 `['child','d','s']`，修复为 `['s']`；新增未知删除部门不造根事实用例。日志 HTTP 首先实际返回数字 106 导致 RED，转字符串后通过。早期 HTTP 夹具遇本机临时目录权限问题，改为带 StaticPool 的内存 SQLite 夹具后获得上述真实行为 RED；没有调整系统目录权限。

验证命令（backend 目录）：

```powershell
./.venv/Scripts/python.exe -m pytest tests/test_task2_department_lifecycle.py tests/test_log_pagination_http.py -q
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m alembic upgrade head --sql
```

最终针对性 **12 passed**；全套 **95 passed、6 MySQL skipped、1 已有第三方 warning**。离线 SQL 生成成功至 0003；无新 schema。没有连接真实 MySQL/飞书、没有派生代理。实现与文档已停止修改，交整体审查限定复审。
