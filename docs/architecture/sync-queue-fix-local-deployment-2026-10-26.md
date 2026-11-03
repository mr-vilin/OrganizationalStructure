# 同步队列修复本机部署与主分支核查

- 日期：2026-10-26（北京时间）。
- 授权范围：部署同步队列修复到此前已明确选择的本机 Docker，检查当前代码是否进入主分支；不包含远端推送或云端部署。
- 修复提交：`db5d2f7b0db22e5b89fb02d8cc6c362ae4b1c831`，已提交到本地 `main`。

## 修复与测试

认领 queued 任务时，初始化完成前排除 reconcile，让已有 initialize 任务能够执行；需要等待初始化的核对与事件分支返回空闲，由主循环按既有 2 秒间隔休眠。保留队列顺序、任务退避、租约、行锁和正常发布事务，不删除或手工修改任务。

本轮重新验证：同步采集、持久化、任务、worker、监听和队列回归 30 项通过；独立 tmpfs MySQL 8.4 中四种场景（初始化优先、核对空闲、重试退避、事件空闲）全部通过。测试库先执行已有迁移，验证后测试容器和网络已清理。业务库没有执行迁移。

## 构建与部署

从上述提交通过 git archive 导出干净源码，严格 npm ci、类型检查、Utoopack 和 Python 包构建通过。基础镜像使用公开 ECR 的官方 Node / Python 镜像源；仓库 Dockerfile 保持原地址。

候选镜像 `organization-directory-runtime:sync-db5d2f7` 同时标记为 `:local`。镜像 manifest 为 `sha256:b79ca13546a6db7a82223e9c321d0b90b3c88e32240e466a74bc60eab894b1df`。前后端元信息相同：0.1.0、development、dirty=false，提交 db5d2f7，构建时间 `2026-10-25T16:15:20.223Z`。仍是开发部署，没有发布 tag。

切换仅执行：

```powershell
docker compose --profile agent up -d --no-deps --no-build --wait --wait-timeout 120 app mcp
```

app 与 MCP 均 healthy、重启计数为 0；运行服务的 31 个真实静态资源正常，HTTP 元信息与后端包一致。MySQL 沿用原容器、配置和卷，迁移仍为 0009。

旧镜像保留为 `organization-directory-runtime:pre-sync-fix-20261026`。需要回滚时将该标签重新标记为 `:local`，以同样命令只重建 app / MCP。代码回滚不会撤销任务已经正常发布的数据；若需要数据恢复，须单独核实并制定恢复方案。

## 任务状态观察

部署前，业务 MySQL 为 8.4.11，实际会话 utf8mb4 / general_ci、UTC、REPEATABLE-READ；目录为空、data_version=0、初始化 pending。旧 reconcile 持续占队首，已有 initialize 的执行次数为 0。

新 worker 按协议等待旧租约到期，未手工清除租约。租约从 generation 17 切换到 18，已有 initialize 从 queued / execution_count=0 变为 running / execution_count=1；采集进度由 60 个部门增长至 109 个部门。

2026-10-26 00:20:57（北京时间）最后观察：初始化仍在 departments 阶段，无错误码、retry_count=0；旧 reconcile 的 execution_count 稳定在 9,768,369，不再反复认领。app / MCP 仍 healthy，重启计数均为 0。上述结果验证队列接手与空转修复已生效，不代表初始化已经完成；候选尚未发布，正式目录仍为空、data_version=0。后续初始化结果及企业覆盖需要按实际任务继续确认，不将 unknown 覆盖改成已验收。

## 主分支核查

| 范围 | 核实结果 |
| --- | --- |
| 主分支名称 | 本地和 GitHub 默认分支均为 main；没有 master |
| 实施分支 | codex/agent-native-impl 的 35bd406 是 main 的祖先，已合入 |
| 另一工作树 | detached a3c3836 也是 main 的祖先；两个实施工作树均无未提交改动 |
| 本次队列修复 | 代码与两组回归已在本地 main 的 db5d2f7 中 |
| 远端真实状态 | HTTP/1.1 的 ls-remote 成功核实 origin/main 为 5db8b4a64e30d27474a10b423b3b893f32eceef7；最初 fetch 曾连接失败 |
| 推送情况 | 修复提交时本地 main 比上述远端领先 41 个提交；没有执行 push |
| 尚未提交的代码 | deploy/mcp-stdio-ssh.ps1，是此前云端接入入口，本次未部署或提交 |
| 尚未提交的文档 | CHANGELOG.md、deploy/README.md 的历史部署记录，以及会话归档、数据库审计、MCP 客户端验收三份文档 |
| 保留的 stash | 仅含 README.md 和 docs/搭建计划.md 的文档差异，不含应用代码；未恢复或删除 |

因此，“现有实施分支已合入本地 main”已验证；“所有工作区代码都已提交”及“所有本地改动都已进入远端 main”均不成立。核查不等于授权推送，本次保留无关工作内容。

本地脱敏证据位于忽略目录 `.cache/`：`sync-fix-before-20261026.jsonl`、`sync-fix-related-tests-20261026.log`、`sync-fix-mysql-tests-20261026.log`、`sync-fix-build-20261026.log`、`sync-fix-after-20261026.json`、`sync-fix-remote-20261026.txt`。
