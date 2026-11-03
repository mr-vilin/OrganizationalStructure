# 初始化向导腾讯云测试部署

- 日期：2026-10-26（北京时间）。
- 授权：用户在完成本地实现与测试后明确要求“你先部署，我来验收”。本次执行现有腾讯云测试环境的镜像更新及必要迁移；未代替用户发起初始化清理、覆盖验收或正式同步。
- 入口：<https://test-organization.bzg.company/initialize>。
- 目标：SSH `tencent_test_col`，`/srv/organization-directory`，Compose 项目 `organization-directory`。未替换本机运行服务或其他项目服务。

## 构建与切换

- 镜像：`organization-directory-runtime:init-20261026-01`；配置 ID `sha256:2e20fd14e2a58b35496a19b49ca2323b137fd504ff42e5d40bcc6cd6a5334933`。
- 版本 `0.1.0`，development，dirty=true，基于 `8152b65858872c1c291a36004d1af79fa58d5ae7` 加当前未提交实现；不代表正式发行或 Git tag。
- 前后端构建元信息一致，构建时间 `2026-10-26T07:57:23.139Z`。独立构建目录包含 219 个受控源码文件及逐文件 SHA-256 清单，不包含配置密钥、缓存或本机依赖。
- 使用既有官方 ECR Node 24 / Python 3.13 固定镜像摘要完成 Linux 多阶段构建，严格安装前端依赖；不改变仓库 Dockerfile、部署拓扑或运行环境配置。
- 上传包 SHA-256 `08314a2a59673c5e42fd48d1bffe68eda4d85eadb2800c706118f81bfaddfd18`，本机与云端核对一致。旧镜像 `cloud-20261024-01` 保留。
- 停止 app/MCP 后制作备份，验证通过再更新 app、migrate、mcp 的镜像引用，运行迁移并启动服务；MySQL 服务未替换。

## 数据库与备份

- 实测 MySQL 8.4.11；库和应用会话为 `utf8mb4` / `utf8mb4_general_ci`，UTC，REPEATABLE-READ。
- 升级前为 `0009_operation_receipt`，升级后为 `0010_initialization_wizard`；前后表结构快照完全一致，实际 schema 检查错误为 0。
- 部门、人员、人员部门关系、门店资料、操作回执前后均为 0，管理员白名单保持 1 条。
- 迁移前唯一排队 reconcile 已隔离，迁移后无 queued/running 任务；初始化 pending、覆盖 unknown，流程 `cleanup_required`。没有创建新的初始化任务。
- 加密备份和原 Compose／构建来源保存于 `/srv/organization-directory/backups/initialization-20261026-01/`，密钥独立保存在受限 `backup-keys` 目录，不在文档中记录密钥内容。
- 数据备份密文 SHA-256 `b059250d4eae2d62fb5a03ec39af9bb4549f486449c1b62c32dbc34c653a9c6b`；加密解密往返一致，并在无网络、tmpfs 的独立 MySQL 8.4 容器实际恢复，版本、空业务目录及管理员数量验证通过。验证容器及临时凭据文件已清理。
- 源码清单、迁移日志、迁移前后快照与公网资源核验结果保存在同一受限备份目录。回退须按[迁移恢复说明](../../deploy/README.md#初始化向导迁移0010)使用配套备份及镜像，不自动恢复旧完成标记。

## 发布后检查

| 检查 | 结果 |
| --- | --- |
| app、mcp、mysql | 全部 healthy，检查时 RestartCount=0 |
| 应用日志 | 新容器启动后未见 Python traceback |
| HTTPS 首页、`/initialize`、live、ready | 200，证书校验启用 |
| 未登录 session、初始化 API | 401 |
| 外部 `/internal` 及子路径 | 404 |
| 飞书登录入口 | 302；回调为本域名 HTTPS `/admin/auth/callback` |
| OAuth cookie | Secure、HttpOnly、SameSite=Lax 保持 |
| 前端资源 | 31 个 JS/CSS 均可通过 HTTPS 读取，哈希与云端镜像完全匹配 |
| 构建信息 | 公网、前端及后端与本次镜像一致 |

本机 Python 默认解析曾返回 getaddrinfo 失败；公共 DNS `223.5.5.5` 返回 `114.132.60.217`，本机通过 curl 指定该解析并保留 TLS 主机名校验后返回 200，云端正常 DNS 的完整 HTTPS 检查通过。未修改本机 DNS 或代理。

## 用户验收入口

管理员访问上述 HTTPS 地址并通过飞书登录，应进入全屏向导，当前先显示“需要按新流程重新初始化”。点击“重新初始化”后从配置检查开始，按需修正设置、提供覆盖依据；前四步通过后才出现“立即同步”。真实企业字段权限、全员／无部门覆盖及最终同步结果由用户继续验收。本次发布检查没有冒充管理员会话或自动填写覆盖依据。

## 同日增量部署：员工类型行式表单

- 用户明确要求部署本次页面修复。员工类型选项改为手动新增、编辑、删除行，提供必填与重复 ID 校验，保存失败保留输入。
- 镜像为 `organization-directory-runtime:form-20261026-01`，配置 ID 为 `sha256:ae425368da229466ce6646c4c2f79776d2dfbcfaf0ca93aa27716b4f7e53bfef`。版本仍为 `0.1.0` / development / dirty=true，构建时间为北京时间 2026-10-26 16:29:13（`2026-10-26T08:29:13.259Z`）。
- 使用上一版已部署的 219 文件源码快照，仅更新 `InitializationPage.tsx`、对应测试、`styles.css` 和构建时的 `CHANGELOG.md`；云端逐文件清单核对通过。沿用固定基础镜像和 Linux 多阶段构建，没有引入工作区其他变更。
- 本地 8 项初始化页面测试、类型检查、Ant Design 检查和生产构建通过；Linux 镜像构建通过。传输包 SHA-256 为 `804eed46be30f651ea6dae3afdde5bbe67c28fdf5645dc10d144a004375de56e`，云端核对一致。
- app、mcp、migrate 的镜像引用统一更新，仅重建 app/MCP；没有执行迁移或重建 MySQL。数据库版本保持 `0010_initialization_wizard`，数据世代、版本、初始化状态、覆盖状态及业务数量均与切换前一致；当前流程为 `precheck_failed`，活动同步任务为 0，管理员白名单保持 1 条。
- app、MCP、MySQL 均 healthy，RestartCount=0。HTTPS 首页、初始化页及 live/ready 均 200，未登录 session/初始化 API 为 401，外部 internal 路径为 404；飞书 HTTPS 回调与 Secure/HttpOnly/SameSite=Lax 校验通过。
- 公网 31 个 JS/CSS 资源全部与运行镜像哈希匹配，新资源包含行式表单并移除了旧 JSON 输入错误提示；公网、前端及后端构建信息一致。未代替管理员提交真实配置或启动同步，真实企业业务验收由用户继续操作。
- 原镜像 `init-20261026-01` 保留。切换前 Compose、部署来源、源码清单、前后状态与公网资源证据位于 `/srv/organization-directory/backups/initialization-form-20261026-01/`。如需回退本次纯页面修复，恢复该目录的 `compose.json` 和 `deployment-source.json`，以 `--no-deps --no-build` 重建 app/MCP 并复核健康状态；无需恢复数据库或降级迁移。

## 同日增量部署：取消人工覆盖依据

- 用户确认本企业不存在无部门人员，并明确要求部署。取消初始化覆盖依据表单、提交接口、预检和启动阻断，以及手工名单补读与精确比对；保留部门全分页采集、字段与关系校验、授权变化门禁。
- 目标仍为 `tencent_test_col` 的 `/srv/organization-directory`，入口 <https://test-organization.bzg.company/initialize>。
- 镜像 `organization-directory-runtime:coverage-20261026-01`，配置 ID `sha256:39cea6e312e58034149b53ce1540b306f2ac94d36c1bf829fa35d16a59dc5185`。版本 `0.1.0` / development / dirty=true，构建时间北京时间 2026-10-26 17:05:54（`2026-10-26T09:05:54.881Z`）。
- 在上一版已部署源码快照上更新 9 个相关文件；逐文件清单核验、Linux 多阶段构建通过。上传包 SHA-256 `d3e4c522610333c4dca8247a522989e37c8db92881fabb39917769fbfb847a4a`，云端核验一致。
- app、mcp、migrate 镜像引用统一更新，仅重建 app/MCP；未运行迁移，MySQL 未重建。数据库版本仍为 `0010_initialization_wizard`，数据世代、版本、初始化状态、覆盖状态、业务数量保持一致，活动任务 0，管理员白名单 1。
- app、MCP、MySQL 均 healthy；HTTPS 首页、初始化页、live/ready 均 200；未登录 session/初始化 API 为 401，外部 internal 为 404；OAuth HTTPS 回调与安全 Cookie 验证通过。31 个公网 JS/CSS 资源与运行镜像哈希一致，构建信息前后端一致，确认覆盖依据表单与调用路径已移除。
- 保留当前 `precheck_failed` 状态。管理员刷新页面后点击第三步“重新检测”，即可重新检查并继续；未代替用户启动预检、清理或业务同步。
- 回退镜像 `form-20261026-01` 保留。切换前 Compose、部署来源、源码清单、前后状态及公网核验证据保存在 `/srv/organization-directory/backups/initialization-coverage-20261026-01/`。回退时恢复该目录的 `compose.json` 和 `deployment-source.json`，以 `--no-deps --no-build` 重建 app/MCP；本次无数据库迁移，不需恢复数据库。
