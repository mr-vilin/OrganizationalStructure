### Spec Compliance

- ❌ Issues found：多阶段镜像、MySQL 持久卷、迁移依赖、三进程监督、同源静态服务、备份命令与恢复后安全重置均已实现；但恢复文档没有实际导入命令，AC01～32 没有逐项记录，本任务要求的全量后端测试、前端构建和迁移 SQL 检查也未形成完成证据。
- ⚠️ Cannot verify from diff：`deploy/supervise.py:43-45` 的 worker/listener 入口以及 `deploy/recovery.py:18,36-37` 的 `OAuthState`、`WorkerLease` 依赖 Task 2 正在补齐，当前只能按约定接口静态检查，无法确认镜像启动和恢复重置可运行。真实 MySQL 事务、恢复演练、Docker 镜像构建与真实飞书联调均被实施报告明确保留为未验收。

### Strengths

- `Dockerfile:1-18` 使用前端构建和 Python runtime 两阶段镜像，把编译后的静态资源放入同一运行镜像，并以非 root 用户运行。
- `compose.yaml:3-42` 为 MySQL 配置 utf8mb4、持久卷和健康检查，迁移成功后才启动应用，应用端口默认仅绑定宿主机回环地址。
- `deploy/supervise.py:14-38` 在任一必要子进程退出时终止其余进程，处理非零退出、意外零退出与启动中途失败；实施报告记录的 3 项真实子进程测试覆盖了这些行为。
- `deploy/web.py:8-22` 支持 SPA 路由刷新，同时明确排除 `/admin`、`/api`、`/health` 等接口前缀，避免把未知 API 伪装成 HTML 成功响应。
- `deploy/recovery.py:17-56` 将世代重置、初始化回退、会话和 API 凭据撤销、任务/事件隔离、租约 fence 与审计置于同一事务，且不会打印或记录 secret。
- `.env.example:1-13` 只提供空值和占位值；`.dockerignore:1-14` 排除环境文件、缓存、依赖、构建产物和备份，降低秘密或敏感备份进入镜像的风险。

### Issues

#### Critical (Must Fix)

- 无。

#### Important (Should Fix)

1. `deploy/README.md:37-55`：恢复章节说明“先导入备份文件”，但只给出了停止应用、运行 `deploy.recovery` 和重新启动的命令，没有创建/清空目标库及调用 `mysql` 导入 `backups/organization.sql` 的可执行步骤。触发方式是运维人员按文档执行恢复；结果只重置当前数据库世代和凭据，实际备份数据从未恢复，却可能在重新启动后误以为恢复完成。应提供目标确认、恢复前快照、导入命令、迁移/兼容检查、`deploy.recovery`、全量核对及验收的完整顺序，并明确哪些步骤会覆盖数据。

2. `docs/运行与验收.md:14-22`：任务要求“逐项记录 AC01～32 状态”，台账却把 32 项压缩成 8 个范围，每个范围只有统一的“待……”状态，无法知道单项 AC 的测试证据、未通过原因或依赖环境。触发方式是按任一具体 AC 做发布判断；审查者无法从台账判断它是否已由单元测试覆盖、仅缺 MySQL、仅缺飞书，还是尚未实现。应列出 AC01 到 AC32 的独立行，逐项链接测试/人工证据，并区分通过、失败、阻塞和未执行。

3. `docs/superpowers/task-4-report.md:3-9`、`docs/运行与验收.md:34-38`：本任务明确要求运行全量后端测试、前端构建和迁移 SQL 检查，报告只记录 deploy tests、Compose 配置、被跳过的集成测试及 recovery `--help`，并称“全栈最终测试待 Task2 和 Task3 修复合入后执行”。因此当前交付没有证明后端全量回归、最终前端产物或迁移链可用。应在 Task 2/3 修复后执行并记录规定命令、版本、通过/跳过数量和警告；真实 MySQL 缺失可以继续标未验收，但不能用它替代无需 MySQL 的完整测试与静态迁移检查。

4. `Dockerfile:18`、`deploy/supervise.py:40-46`、`deploy/recovery.py:18,36-37`：生产镜像的唯一 CMD 无条件启动 `app.sync.worker` 和 `app.feishu.listener`，恢复命令也在运行期导入/更新 `OAuthState`、`WorkerLease`；这些对象在当前审查包中尚未落地，实施报告同时承认依赖 Task 2。触发方式是现在构建并启动镜像或执行恢复；可能在子进程/导入阶段立即失败，监督器随后关闭整个实例。此项属于跨任务集成阻塞，不要求 Task 4 自行复制实现，但 Task 2 合入后必须用最终镜像做启动、SIGTERM、子进程失败和恢复命令的联调验收，才能解除。

#### Minor (Nice to Have)

1. `compose.yaml:14-18`：MySQL 健康检查没有传用户名/密码，只证明服务端口开始响应；数据库授权或目标库配置错误要到 migrate 容器才暴露。当前依赖链仍会因迁移失败阻止 app 启动，因此不会产生错误的健康应用，但排障信息较晚。可改为使用受限业务用户执行一个简单查询，同时避免在进程列表或日志中暴露密码。

2. `deploy/recovery.py:61-62`：`--application-stopped` 是调用者声明，程序本身不验证 HTTP、worker 和 listener 是否真的停止。文档已明确要求先停应用，风险主要来自脱离文档直接调用 CLI。可在恢复流程中增加部署层检查或数据库维护锁，让误操作更难发生。

### Assessment

**Task quality:** Needs fixes

**Reasoning:** 部署和恢复代码的结构与安全方向合理，但恢复指令缺少真正的数据导入步骤，32 项 AC 台账不可逐项审计，且最终测试、构建、迁移和 Task 2 入口联调尚未完成；这些都是发布前必须补齐的交付证据。
