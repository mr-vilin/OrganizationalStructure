# 环境登记与标准发布流程

## 默认规则与授权

代码完成并通过相关测试后，默认部署本地 Docker。“部署”未指定环境时也指本地。线上测试、正式环境必须由用户当次明确要求，不能从历史任务、截图、上次发布目标或默认参数推断授权。口头与文字指令均可，执行远端发布时用 `--authorization` 记录原指令摘要；该参数不创造授权。

本文件与 `environments.json` 是目标信息来源；`release.py` 是统一入口。不要从聊天历史、临时目录或某次构建日志重新拼装发布流程。发布前仍要执行标准检查，信息固化不等于免除验证。

## 环境台账

核实日期：2026-10-26，北京时间。

| 项目 | 本地 Docker | 线上测试 | 正式 |
| --- | --- | --- | --- |
| 状态 | 已建立，Docker Desktop Linux | 已建立，腾讯云测试主机 | 用户确认尚未建立，脚本禁用 |
| 主机入口 | 当前 Windows 开发机 | SSH 别名 `tencent_test_col`，既有可信主机密钥 | 待确认 |
| 部署目录 | 仓库根目录 | `/srv/organization-directory` | 待确认 |
| Compose | `compose.yaml` | `compose.json` | 待确认 |
| Compose 项目 | `organization-directory` | `organization-directory` | 待确认；不得与测试数据卷混用 |
| 应用入口 | `http://127.0.0.1:8000`；仅用于本机检查，正式登录 HTTPS 入口待登记 | `https://test-organization.bzg.company` | 待确认独立 HTTPS 域名与回调 |
| 容器 | app、mcp、mysql；migrate 为一次性服务 | 同左 | 沿用既定拓扑，实例与凭据独立 |
| 数据库 | 已授权迁移至 `0010_initialization_wizard`；MySQL 8.4.11 | 实测 `0010_initialization_wizard`；MySQL 8.4.11 | 待创建及实测，不能假定同测试 |
| 最近镜像 | `organization-directory-runtime:release-20261026-093353-8a68260a` | `organization-directory-runtime:coverage-20261026-01` | 无 |
| 凭据来源 | 仓库 `.env` 和 Docker Desktop 当前身份 | 远端原 Compose／受限配置、SSH 当前身份、`sudo -n docker` | 独立配置，禁止复制测试凭据 |

这里的版本和镜像是核实快照；每次运行 `inspect` 获取当前状态。`ORG_AGENT_ENVIRONMENT` 是能力安全策略字段，不能据它的值认定部署主机是测试或正式环境。

## 固定工具与制品

- Windows：仓库 `backend/.venv/Scripts/python.exe`（Python 3.13）、Node.js 24、Docker Desktop Linux、Docker Compose、OpenSSH。远端需要 Python 3 与非交互 sudo Docker 权限。
- `build-images.json` 固定此前已经跑通的官方 ECR Node 24 / Python 3.13 镜像摘要。构建脚本只替换 Dockerfile 的 FROM 地址，不复制维护第二份 Dockerfile；基础镜像升级需更新该文件并验证。
- `build` 从 Git 受控与未忽略文件生成源码快照，包含 backend、frontend、deploy、scripts 和构建入口，不携带 `.env`、本机依赖、缓存或 Git 历史。制品保存于 `.cache/artifacts/<release-id>/`，包含逐文件 SHA-256、提交、dirty、schema head、镜像 ID、构建信息和镜像压缩包校验值。
- 每次构建使用独立标签，禁止覆盖既有制品。测试、正式部署必须明确传入制品目录。正式环境启用后必须使用干净版本标签构建，并提升已成功部署测试的同一个镜像，不现场重建。
- 制品同时记录构建端 `image_id` 与从 Docker 导出包读取的 `image_config_id`。containerd 和经典存储可能对同一制品返回不同 ID；目标端必须匹配其中一个摘要，随后以目标端实际 ID 固定 Compose 并核验运行容器。传输仍校验完整压缩包 SHA-256，不因 ID 表示差异跳过制品校验。

## 常用命令

所有命令从仓库根目录运行。以下使用 PowerShell；默认 Python 路径无需激活虚拟环境。

```powershell
# 仅看固定目标，不连接或改变环境
backend/.venv/Scripts/python.exe deploy/release.py plan
backend/.venv/Scripts/python.exe deploy/release.py plan --environment test

# 只读：现有数据库版本、状态、对象数量；不输出个人资料与凭据
backend/.venv/Scripts/python.exe deploy/release.py inspect
backend/.venv/Scripts/python.exe deploy/release.py inspect --environment test

# 默认本地：构建并部署；schema 不一致会停止，不自动迁移
backend/.venv/Scripts/python.exe deploy/release.py deploy

# 只构建，输出 artifact 路径；已有制品可直接部署本地
backend/.venv/Scripts/python.exe deploy/release.py build
backend/.venv/Scripts/python.exe deploy/release.py deploy --artifact .cache/artifacts/<release-id>

# 只有当次获得“部署测试环境”的明确指令后才运行
backend/.venv/Scripts/python.exe deploy/release.py deploy --environment test --artifact .cache/artifacts/<release-id> --authorization "用户本次明确要求部署测试环境"

# 发布后复核，不触发同步或初始化
backend/.venv/Scripts/python.exe deploy/release.py verify
backend/.venv/Scripts/python.exe deploy/release.py verify --environment test

# 无迁移发布的应用回退；release-id 必须是当前发布的 ID
backend/.venv/Scripts/python.exe deploy/release.py rollback --release-id <release-id>
backend/.venv/Scripts/python.exe deploy/release.py rollback --environment test --release-id <release-id> --authorization "用户明确要求回退本次测试发布"
```

`<release-id>` 是占位符，替换成 build 输出的真实目录名。远端回退与发布都是写入，需要当次授权。正式环境当前无可执行命令；配置建立、备份策略确认后才允许开启 `configured`。

## 每次发布的固定步骤

1. 按本次授权选择环境，检查工作区与待发布范围；无关未提交改动先隔离。运行相关测试、类型检查、构建检查及 `node scripts/versioning.mjs check`。制品清单供复核，不能把脏快照称为正式发行。
2. `inspect` 核实实际迁移版本与初始化／同步状态。脚本拒绝有 queued/running 任务、checking/running 初始化流程的切换。schema 不匹配转数据库迁移手册，禁止顺手 `upgrade head`。
3. `build` 生成唯一制品。远端通过既有 SSH 身份上传，SHA-256 一致后才 `docker load`。不自动接受陌生主机密钥，不传输运行凭据。
4. 保存当前 app/MCP 的不可变镜像 ID、manifest、目标、前状态与部署来源。以新镜像只读检查真实数据库就绪，不启动 supervisor，不执行迁移。
5. 停止 app/MCP，再次只读核验没有任务进入执行；以 `--no-deps --no-build` 切换并等待健康。MySQL、数据卷和迁移服务不重建。
6. 验证 app/MCP healthy、运行镜像 ID、首页和初始化页、live/ready、未登录 API 边界、前后端构建元信息及所有公网 JS/CSS 哈希。HTTPS 额外验证 internal 路径隔离、飞书 HTTPS 回调及安全 Cookie。未完成初始化的实例必须保留数据世代、版本、业务数量和流程状态；已初始化实例正常事件处理可能改变数据，不能把正常业务变化误判为必须回退。
7. 验证失败自动恢复旧镜像并验证回退；若回退也失败，明确报告失败，不宣称恢复成功。成功后保留部署与验证记录，报告目标、镜像、构建时间、验证结果及尚未完成的业务验收。

## 配置持久化、证据与回退

标准脚本使用原 Compose 加 `<部署目录>/.cache/deployment-image.json` 镜像覆盖文件；只含 app/mcp/migrate 的镜像 ID，不含凭据。此覆盖文件是**后续启动的必要部分**：不要绕过脚本直接 `docker compose up --build`，否则可能回到原 Compose 的旧镜像。只读 exec、ps 可使用原 Compose。

部署来源：`.cache/deployment-source.json`。每次发布证据：`.cache/releases/<release-id>/`，含 `previous-images.json`、`previous-source.json`（若有）、`before.json`、`manifest.json`、`target.json`、`after.json`、`verification.json` 和回退验证记录。远端文件按 umask 077 创建；本地沿用仓库 Windows ACL，禁止公开分享运行证据目录。镜像与证据不自动删除。

发布使用 `.cache/deployment.lock` 防并发；进程异常退出后可能保留锁，必须确认不存在进行中的发布才人工删除空锁目录。禁止用删除锁解决未知发布状态。

本脚本的回退点是应用镜像／来源记录，不是数据库备份。部署过程不修改数据库结构，不能把镜像回退当作数据库回滚。涉及迁移、恢复或数据清理时，必须另行做数据库加密备份、恢复演练及前后结构检查，遵循 [README 的数据库迁移与恢复流程](README.md#初始化向导迁移0010)。

历史测试发布使用 `/srv/organization-directory/backups/initialization-coverage-20261026-01/` 等目录，其回退按 [历史部署记录](../docs/architecture/initialization-cloud-deployment-2026-10-26.md) 执行；新脚本不伪造旧发布的 release-id。

## 当前限制和验收边界

- 2026-10-26 用户后续明确授权本地加密备份、恢复演练、`0009 → 0010` 迁移及发布，已完成。当前 pending / cleanup_required，业务数据保留，未清理或同步，见[本地发布记录](../docs/architecture/local-initialization-deployment-2026-10-26.md)。未来迁移仍需单独授权。
- 正式环境尚未建立，首次建库、初始化、TLS、备份存储与恢复演练不在常规镜像更新脚本中。创建后分别核实主机、目录、独立配置与数据库，更新台账并演练，才允许正式发布。
- 2026-10-26 已通过标准 release.py 完成本地真实切换和发布后验证；远端标准流程仍须分别验收，不以本地成功代替远端证据。
- `inspect` 不修改业务数据；`verify` 的 HTTPS OAuth 检查会创建正常的短期登录 state，但不登录、不操作业务。本地 HTTP 检查不替代真实 HTTPS 登录验收。
- Docker 管道／CLI 身份受沙箱隔离时，按项目规则使用同用户非受限进程复核；不能悄悄改部署目标或改认证配置。

## 本轮脚本验证记录

2026-10-26：`release.py inspect` 与 `verify` 在本地、测试环境均通过。本地同时核实宿主机 8000 映射端口；两环境均核验 app/MCP 健康、构建信息与 31 个 JS/CSS 资源一致。测试环境额外通过 HTTPS internal 隔离、飞书回调和 Cookie 检查。未执行本轮镜像切换、数据库迁移或业务同步。

`deploy/tests/test_release.py` 的 10 项测试覆盖远端授权、正式环境禁用、制品损坏、迁移／活动任务阻断、发布锁、失败恢复、恢复失败、跨迁移回退保护及停止服务后的只读探测。Windows 沙箱临时目录受限时使用仓库内测试目录：

```powershell
$env:PYTHONUTF8 = '1'
$env:TMP = Join-Path (Get-Location) '.cache/release-tests-tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null
backend/.venv/Scripts/python.exe -m unittest deploy.tests.test_release -v
```
