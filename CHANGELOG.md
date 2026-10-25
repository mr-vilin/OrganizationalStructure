# 产品版本记录

产品版本遵循 [版本规范](docs/versioning.md)，唯一声明为根目录 [version.json](version.json)。本台账以版本为单位，允许同日多个版本；日期使用北京时间。已发布版本内容不得覆盖，开发改动先收集到 Unreleased。

## [Unreleased]

### 变更

- 管理端按 Ant Design Pro 6 工程迁入 Umi Max / Utoopack，统一 ProLayout、PageContainer、受控 ProTable 与人员 ProDescriptions；保留业务协议，补齐任务详情 URL 生命周期及静态 chunk 服务。

- 经用户确认，尚未正式上线，产品版本从旧开发编号重新设为 0.1.0；原记录归档至 [旧编号历史](docs/releases/legacy-development-history.md)。
- 建立 SemVer 规范、统一版本来源、构建元信息、系统信息页运行版本展示及版本 CI 校验。

### 迁移与回滚

- 数据库迁移：无；不新增版本表，不改变现有业务数据版本。
- 回滚：回退本批代码及对应镜像；数据库不需要回滚。本次不修改 Git 历史或已有 tag。

### 验证

- 2026-10-25：Pro 迁移前端完整回归 32 项、相关后端 7 项、版本规则 7 项通过；Windows 和 Linux 构建、隔离 Docker 的 31 个静态资源、元信息及浏览器响应式验证通过。真实企业环境与部署尚未验收，见[迁移实施记录](docs/architecture/ant-design-pro-migration-acceptance-2026-10-25.md)。

- 2026-10-24：版本规则测试 7 项、后端版本与静态页面测试 5 项、系统信息页测试 3 项通过；TypeScript/Vite 构建通过。
- 独立 Docker 镜像中前端、后端及安装包元信息一致，均为 0.1.0、development、releaseDate=null；未认证版本接口 401，认证后返回元信息并禁止缓存。
- CI 配置已添加并解析校验，尚未推送或在 GitHub 执行；版本规则专项验证时未替换运行服务、未执行数据库迁移。历史验收记录不作为本次验证证据。

## 开发基线

- 当前版本：0.1.0，建立日期：2026-10-24。
- 状态：开发初始阶段，尚未正式发布或上线；本节不属于发行记录。
- 正式或预发布时新增 `## [版本] — YYYY-MM-DD` 记录，并通过发布校验后创建对应 tag；当前没有发行记录和发布日期。
