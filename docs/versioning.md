# 产品版本与发布规范

## 依据与适用范围

本项目采用 [SemVer 2.0.0](https://semver.org/lang/zh-CN/)。本文件是项目版本规则的唯一正文；文件布局、开发流程、0.x 递增策略是项目约定，不属于 SemVer 的额外官方要求。

2026-10-24 用户确认：尚未正式上线，产品版本重新从 **0.1.0** 开始。此版本是开发初始基线，不代表已经发布或上线。旧编号及当时的验证记录见 [旧编号归档](releases/legacy-development-history.md)，不得将旧记录的验收结果当作新版本的当前证据。

## 兼容承诺与编号

公开契约包括：对外 HTTP API 和 MCP 工具的名称、参数、返回结构、错误及已承诺的业务行为；稳定 ID、数据语义和一致性协议；公开支持的部署配置和升级方式。新增可选字段也必须检查严格解析客户端的兼容性，不能仅根据语法认定兼容。

| 变化 | 1.0.0 起 | 0.x 开发阶段的项目约定 |
| --- | --- | --- |
| 破坏公开兼容承诺 | major 加 1，其余清零 | minor 加 1，patch 清零，并明确记录破坏性变化 |
| 兼容新增能力或公开 API 弃用 | minor 加 1，patch 清零 | minor 加 1，patch 清零 |
| 兼容问题修复 | patch 加 1 | patch 加 1 |

0.x 的公共契约尚未稳定，不作稳定 API 承诺；仍须描述兼容影响和升级要求。正式形成稳定公共契约时，经明确确认进入 1.0.0，不能仅因部署到某个环境就自动升级到 1.0.0。

同批发布只按最高影响级别定一次版本。布局、文字、性能调整按实际影响判断；修错通常属于 patch，新增能力通常属于 minor。数据库内部实现变化不自动等于公开 API 破坏，但迁移、回滚及部署兼容影响必须审查。未发布的内部重构不要求单独发布；重新交付改变后的软件内容时不得复用已经发布的版本。

版本值使用 X.Y.Z，整数不得带前导零；文件内不带 v，Git tag 使用 vX.Y.Z。预发布使用 -alpha.N、-beta.N、-rc.N，例如 0.2.0-rc.1；同一目标版本的后续候选增加预发布编号。构建信息可使用 +build.N 或 Git SHA，构建信息不参与 SemVer 优先级比较。禁止将 patch 作为开发次数累计，禁止使用 max(本地 patch, 线上 patch) + 1 的公式。

## 唯一来源与运行版本

- 根目录 version.json：当前代码声明的产品版本，唯一手工维护入口。当前为 0.1.0。
- CHANGELOG.md：Unreleased 收集尚未发布的改动，每个准备发布的版本一条记录，格式为 `## [0.1.0] — YYYY-MM-DD`。允许同日多个版本，按发布时间倒序排列；日期使用北京时间，不将构建时间当发布日期。
- Git tag：绑定正式或预发布版本与提交；GitHub Release 展示说明和产物。0.x 的发行也可使用 tag/Release，但不代表稳定 API 或生产上线。
- build-info.json：构建生成的版本、提交、工作区状态、构建时间、发布状态和发布日期。不得手工编辑或提交。系统信息页读取前端构建元信息，并查询受管理员认证保护的服务端元信息，发现不一致时提示刷新或检查部署。
- 技术包版本仍由 frontend/package.json、backend/pyproject.toml 管理；API 契约版本、Alembic revision、dataset_epoch/data_version 分别管理。数字相同不代表同一种版本。

开发构建的 stage 为 development，releaseDate 为 null，即使 CHANGELOG 已准备好记录，也不能宣称已发布。只有通过 tag 校验、以 ORG_RELEASE_TAG 构建的产物，stage 才为 release 或 prerelease；0.x 页面始终标明开发初始阶段。未提供可核实提交时显示 unknown；脏工作区构建明确标记 dirty。

产品版本不落业务数据库；镜像回滚时元信息随镜像回滚。未来如需部署审计，可另行设计环境、版本、提交、镜像摘要、时间、操作者、结果等记录；本次不新增表、不执行数据库迁移。

## 开发与发布流程

1. 日常 PR 更新 Unreleased，或说明无产品行为变化；不要求每次合并提升版本。合并前运行 `node scripts/versioning.mjs check`。
2. 发布 PR 汇总本批变化，人工审查兼容性并决定版本，更新 version.json，新增对应日期的版本记录，保留迁移、回滚和验证证据。不同发布版本不得重复，已发布记录不得被后续 PR 改写。
3. CI 使用 `--base-ref` 检查既有版本记录不可变和版本递进；使用 `--release` 检查本版本记录及清零规则。自动检查不能证明业务兼容性，PR 必须注明版本级别和理由。
4. 对确定的干净提交创建 vX.Y.Z tag。tag CI 校验版本、记录与实际 tag 提交一致，构建元信息并运行测试和构建。GitHub Release、推送镜像和部署仍按任务授权执行；CI 不自动将代码部署到生产。
5. 发布和部署分别记录。部署指定镜像并验证实际前后端版本；回滚选择旧镜像，不回写旧镜像中的版本号。本次建立的 CI 只是版本及相关构建门槛，不代替真实 MySQL、飞书或生产验收。

```powershell
# 本地校验及相关测试
node scripts/versioning.mjs check
node --test scripts/versioning.test.mjs

# 发布准备检查（需要先写好对应记录）
node scripts/versioning.mjs check --release

# 已创建 tag 后的发布构建；替换为实际值
$env:ORG_RELEASE_TAG = 'v0.1.0'
$env:ORG_COMMIT_SHA = git rev-parse HEAD
node scripts/versioning.mjs build-info --output build-info.json
# Docker 接收相同参数，前端与 Python 包复制同一份元信息
docker build --build-arg ORG_RELEASE_TAG=$env:ORG_RELEASE_TAG --build-arg ORG_COMMIT_SHA=$env:ORG_COMMIT_SHA --build-arg ORG_SOURCE_DIRTY=false -t organization-directory-runtime:0.1.0 .
```

发布构建必须提供完整提交 SHA。本地开发可不设置这两个环境变量，自动读取 Git 状态。Docker 构建上下文不含 .git；普通本机镜像若希望显示提交，显式传入 ORG_COMMIT_SHA，并用 ORG_SOURCE_DIRTY=true 标记未提交修改。正式发布构建由 CI 从 tag 对应的干净提交构建，禁止使用脏工作区。

## 旧规则替代

本文件及 ADR 0003 取代 ADR 0001 中“每个产品变更 PR 都递增并手工同步页面”的流程。旧编号只作历史，不参与新序列的比较、递增和校验。0.1.0 是用户明确授权的一次重新编号；后续已发行版本不得倒退或重新编号。
