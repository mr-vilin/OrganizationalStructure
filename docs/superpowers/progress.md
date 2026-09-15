# SDD ledger — plan: docs/superpowers/plans/2026-09-15-system-build.md

## 预检

| 任务/接口 | 检查结果 |
| --- | --- |
| Task 1 | 模型、权限、领域与查询在 backend 内闭合；输出接口说明供后续消费 |
| Task 2 | 消费 Task 1 持久化与事务服务；在 Task 1 完成后执行以避免文件冲突 |
| Task 3 | 消费后端 envelope、CSRF、分页；独立 frontend 目录 |
| Task 4 | 消费 app.main:app、worker 入口和 frontend/dist；依赖 1～3 |
| 1 / 2 | 会话、模型、发布锁共享；先接口确定再适配 |
| 1 / 3 | HTTP 契约由 Task 1 输出，Task 3 不凭空定义字段 |
| 2 / 4 | 后台执行入口需写入报告，由部署配置消费 |
| 3 / 4 | 前端产物固定 frontend/dist，由镜像复制 |

Ruling: 当前无 Git 仓库，按目录与文件清单隔离任务，保留台账而不创建 worktree — 项目目录专用于本系统且 .git 只读 — 代价是本轮没有提交历史可供回退。

## 状态

- Task 1: complete（代码范围完成；26 项测试及离线迁移通过；复审通过，见 task-1-rereview.md；真实 MySQL 验收保留）
- Task 2: complete（root 95 passed / 6 MySQL skipped；整体 F1/F5 限定复审通过；真实环境验收保留）
- Task 3: complete（root 25 项测试、生产构建、Ant Design lint 0；最终同步中心 Edge 回归及整体复审通过）
- Task 4: complete（代码/文档范围；部署5项测试、配置/迁移/入口检查通过，限定复审通过；真实环境验收保留）
- 环境：Python 3.13.14 / Node 24.18.0；Docker 引擎未启动；未发现已配置的飞书凭据。
- 用户确认：先完成代码，稍后提供数据库环境；不再尝试启动 Docker 或连接未知数据库。
- Task 4 局部进度：进程监督器 3 项真实子进程测试通过，覆盖错误退出、意外正常退出和启动失败时兄弟进程清理。
- Task 3 局部进度：前端依赖与锁文件、Vite/TypeScript 配置、HTTP 请求层已创建；4 项请求契约测试通过（会话与 CSRF、409、非 JSON 错误、缺失业务 envelope）。
- Task 4 配置验证：生产与测试 Compose 均通过 `docker compose config --quiet`（生产用 --no-env-resolution）；未启动数据库。
- 飞书契约核验完成：见 `feishu-contract-check.md`。scopes 无全员确认字段，无部门人员覆盖仍需真实联调；后续实现必须显式展示未知覆盖。
- Task 4：同源静态入口 `deploy.asgi:app` 包装后端 `app.main:app`；静态回退保留未知 API 的 404；部署侧共 5 项测试通过。
- Task 1 审查：8 项 Important + 2 项 Minor，已交原实现代理集中修复（轮 1）；报告 `task-1-review.md`。
- Task 1 修复轮 1 已提交复审：26 项测试通过；冻结迁移、资料 patch、会话 JOIN、原子凭据、安全日志、UTC 时间与任务锁已修复；复审范围限定原问题和直接回归。

Ruling: 在后端修复复审期间推进独立前端任务，飞书任务随后执行 — 前端只依赖已固定 HTTP 契约且目录独立，没有同时派发多个实现代理 — 若后续契约必须调整，需同步修改请求适配层。
- Task 3 请求基础层：8 项测试与 TypeScript 类型检查通过，增加旧请求竞争保护、版本一致的完整分页拉取与重复游标保护。
- Task 4 集成测试代码：增加 4 项真实 MySQL 用例，使用独立 `_test` 库和外层回滚；当前实际执行结果为 4 skipped（未提供数据库），没有报告为通过。
- Task 2 接续检查：投影发布需完善 preview 后代/实际受影响人数、主部门质量保持及归属路径，已写入 Task 2 brief，必须在最终验收前处理。
- Task 3 审查：8 Important、2 Minor，详见 task-3-review.md；修复待当前 Task 2 实现代理完成后统一派发，避免同时运行多个实现代理。
- Task 3 浏览器首轮：Playwright + 系统 Edge，1440×1000、390×844；使用请求拦截测试夹具，非真实业务联调。无 pageerror、无横向页面溢出；成功读取树与人员，复现预览遮挡保存。截图在系统临时目录 org-desktop.png / org-mobile.png / org-preview.png。
- Task 4 恢复代码：deploy.recovery 提供恢复后新世代与凭据撤销事务；新增 2 项 MySQL 恢复测试，当前总计 6 skipped。仍未执行真实数据库恢复。
- Task 2 代码完成：SDK 7 类事件构建与离线迁移通过；范围移动回查、缺失字段保留、绑定隔离、事件失败可见与租约 fence 已有行为测试。真实MySQL/企业仍未验收。
- Task 4 审查：4 Important（导入步骤、32项台账、最终静态回归、Task2入口集成），2 Minor。后续补齐代码/文档及无需数据库的检查，真实环境验收按用户要求保留。
- Task 4 真实 HTTP 浏览器检查：`deploy.asgi:app` 在未配置数据库/身份环境启动，Edge 1080×900 验证登录门禁与重新检查；无 pageerror；health/live 200、health/ready 503、auth/session 401、未知 API 404，均 JSON。不等于真实业务联调。截图位于系统临时目录 org-unconfigured.png。
- Task 2 审查：4 Important（覆盖失效恢复、登录映射不可覆盖、未知部门不得编造active事实、确认离职管理员撤权），2 Minor。修复brief已准备，待前端当前实现结束后派发。
- Task 4 验收台账已展开 AC01～32 独立行，分别记录代码证据、修复中与真实联调未执行状态。
- Task 2 根代理接口检查：公开读服务注入 OperationalError，实际 500 text/plain，缺少统一错误 envelope；已并入修复轮1，要求稳定 JSON 与 SQL 参数隐藏。
- Task 3: fix round 1/5（11原项已关闭，3原项仍开；R1直接回归包含draft覆盖、无法展开、无版本子请求）；已派frontend修复轮2，见task-3-fix-2-brief.md。
- Task 2: fix round 1/5（3/4原Important及错误封装已关闭；AC25仍开：明确inactive受未知部门连带延后）；73passed/6skipped，修复轮2 brief已准备。
- Task 2 修复轮2根代理验证：83 passed、6 skipped、1 Starlette/AnyIO 第三方弃用警告；Alembic 0001→0002→0003 MySQL 离线 SQL 通过；HTTP/worker/listener/recovery 模块及 OAuthState/WorkerLease/PendingFact 导入通过。
- Task 3 修复轮2浏览器：Edge 1440×1000，两部门409保留草稿并以新版本再次提交、手动三级树/search/clear、日志来源与操作者过滤/重置、每日03:00设置通过，无pageerror。390×844选择部门后发现页面宽788px，和整组409无上限一并交原代理修复轮3。
- Task 4 最新 TestClient：静态组织页200，live200、ready503、session401、未知管理API404，API均JSON。无数据库与登录配置下保持拒绝访问业务；未执行真实MySQL/飞书或镜像构建。
- Task 2 R2 已获独立限定复审通过。整体审查另发现 F1：部门明确删除未结束直接当前关系，且父引用不可读会延后可信删除。root SQLite夹具复现inactive部门仍保留active关系和旧门店投影，已准备 task-2-final-fix-brief.md，待当前前端停止后集中修复。
- 整体审查代理 final_review 已审后端/部署和稳定前端页；F2首次preview409、F3同步中心状态契约与终态刷新、F4人员质量/归属路径、M1日志对象类型并入当前前端R3。无新增Critical。整体结论暂Changes requested，修复后限定复审。

## 最终结果（替代上方过程状态）

- 整体 F1～F5、M1 已关闭，final-review.md 最终 Approved，无开放 Critical/Important。
- root 最终验证：后端95 passed / 6真实MySQL skipped；前端25 passed、build通过、Ant Design 0 issues；deploy5 passed。数据库/企业/容器镜像与恢复演练未执行。
- Task4原4项Important已关闭，task-4-rereview.md为Approved。非阻断加固建议保留：MySQL健康检查仅ping、恢复CLI的停应用参数为操作人声明；完整恢复操作顺序已明确要求停应用并确认目标。
- 浏览器通过组织/门店版本重读与重试停止、批量冲突保留与重提、手机页面宽度、日志过滤、同步meta时间/终态三组刷新/事件重试。测试夹具与真实企业数据明确区分。
- 非阻断工具提示：Starlette/AnyIO弃用、jsdom伪元素支持限制、Vite主包约1.278MB拆包建议。未隐藏这些提示。
- 无Git仓库，保留本目录代码、原型、截图、计划和审查记录，不创建或伪造提交。
