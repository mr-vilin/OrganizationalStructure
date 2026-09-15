# Task4 实施报告

交付：多阶段 Dockerfile、MySQL 8.4 Compose 与独立测试配置、三进程监督（HTTP/worker/listener）、同源 SPA 静态服务、备份说明与恢复后世代/凭据重置 CLI。配置模板不含真实密钥。

验证：部署5项测试通过（真实子进程退出清理及静态页面/API回退）；两个Compose配置检查通过；后端最终95 passed、6 MySQL skipped，前端最终25 passed、生产构建与Ant Design lint通过。恢复命令 --help 成功。真实MySQL跳过不计为通过。

恢复需停止应用并显式 --application-stopped、--actor，可选 --admin-open-id 作线下核验后的管理员恢复。原子重置 epoch/init、撤销所有session/APIkey/OAuthstate、租约fence、旧任务/事件隔离、写审计。Task2 的 OAuthState / WorkerLease 已实现，导入检查通过。

未执行：Docker镜像构建、真实MySQL事务/恢复、真实飞书。用户已授权先代码，后提供数据库。

## 修复与最终验证

- 恢复文档补齐明确目标库的现状备份、DROP/CREATE、备份导入、迁移、新世代与凭据重置、启动核对；Bash 使用 `set -euo pipefail`，前置失败会停止后续破坏性步骤。仅交付指令，没有执行数据覆盖。
- 验收台账拆为 AC01～32 独立行，分别关联代码证据及真实环境未执行项。
- 最终后端独立执行：95 passed、6 MySQL skipped、1 Starlette/AnyIO 弃用 warning；Alembic 0001→0002→0003 离线 SQL 退出 0。
- HTTP、worker、listener、recovery 入口以及 OAuthState/WorkerLease/PendingFact 导入成功；无配置 TestClient 的静态页200，live200、ready503、session401、未知API404，API均JSON。
- 部署5项测试再次通过。最终前端9个文件25项通过，TypeScript/Vite构建通过，Ant Design lint为0；浏览器同步终态/版本冲突/手机布局等受控夹具验证通过。jsdom伪元素提示及1.278MB主包体积建议已在验收台账记录。
- Task4 原审查第4项的源码依赖缺失已消除；最终镜像的三进程与实际数据库启动/停止/恢复验证仍待外部环境，不能标记镜像联调通过。
