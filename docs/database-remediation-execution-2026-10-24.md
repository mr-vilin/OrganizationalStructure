# 本机数据库整改执行记录

日期：2026-10-24。用户在隔离 MySQL 验收完成后授权“开始执行”，随后确认“暂未配置，先完成本机数据库迁移”。本记录仅覆盖该本机环境；不代表测试、生产或其他实例已迁移，也不代表组织初始化和飞书覆盖验收完成。

## 目标与版本

| 项目 | 实际结果 |
| --- | --- |
| Compose 项目 | `organization-directory` |
| 数据库实例 | 本机 `127.0.0.1:13307`，MySQL 8.4.11 |
| 数据库 | `organization` |
| 迁移前版本 | `0006_column_comments` |
| 迁移后版本 | `0008_session_digest` |
| 部署代码 | `d3ed60d` |
| 应用镜像 | `sha256:e2688f65aa9a54211ba1c92d71dcff80a46312d2343b1640f20fdcd386eece71` |
| 部署方式 | 当前 Dockerfile 构建 app/migrate，迁移成功后仅重建 app |

## 停写、备份与执行

1. 只读核实目标、版本、结构及会话数量。新 app/migrate 镜像构建成功后停止 app，容器状态为 exited；HTTP、worker、监听均随之停止。未发现容器外运行的相应 Python 服务，停写后数据库其他连接数为 0。
2. 再次执行冻结元数据检查、唯一键冲突检查、外键兼容性及孤儿检查，21 张业务表均通过。比较样本确认 `general_ci` 对大小写、重音及尾空格不敏感；既有唯一键无冲突。
3. 保存受限结构、行数及聚合数据指纹快照。执行 `mysqldump --single-transaction --routines --triggers --events --set-gtid-purged=OFF --no-tablespaces organization`，备份在内存中使用 Windows 当前用户 DPAPI 加密，不将旧会话令牌作为明文 SQL 文件落盘。
4. 加密备份位于 `backups/remediation-20261024-live/organization.sql.dpapi`，大小 32,422 字节；目录 ACL 仅授予当前 Windows 用户及 SYSTEM。解密回读与备份原字节一致。解密依赖该 Windows 用户的 DPAPI 密钥，不能把文件当作普通 SQL 导入。
5. 将加密备份在内存解密，导入新建的 `tmp_org_verify_20261024_test`。比对 21 张表完整结构及全部行一致后，才运行 `docker compose run --rm --no-deps migrate`；退出码为 0。
6. 迁移后先完成结构、数据与会话校验，再运行 `docker compose up -d --no-deps --no-build --wait app`；退出码为 0。验证完成后删除恢复临时库，保留加密备份和受限校验文件。

备份目录受 Git 与 Docker 构建上下文忽略规则保护。目录中的 `before.json`、`after.json` 为结构/校验记录，不含密码、原会话值或摘要清单。本次辅助校验工具位于 `backups/verify_live_remediation.py`。

## 验收结果

| 验收项 | 结果 |
| --- | --- |
| ORM 与实际结构 | 0 项差异，迁移版本为 `0008_session_digest` |
| 数据库、表及普通文本排序规则 | `utf8mb4_general_ci`，稳定 ID/业务键保留 `utf8mb4_bin` |
| 数据保留 | 21 张表行数一致，除 `admin_session` 预期转换外全部行指纹一致 |
| 管理员会话 | 总数仍为 5；迁移前已过期 5、已撤销 3；迁移后全部 5 条撤销 |
| 会话转换 | 原 ID 全部替换；摘要集合与旧令牌 SHA-256 集合的聚合指纹一致；无空值、重复或不安全记录 |
| 旧认证值拒绝 | 5 个旧 Cookie 及 5 个摘要值分别请求 `/admin/auth/session`，全部返回 401 |
| 进程 | HTTP、worker、飞书监听均运行；检查时应用重启计数为 0 |
| 实际连接会话 | 从 MySQL performance_schema 读取并按客户端 PID 对应三个进程：字符集 utf8mb4、连接排序规则 general_ci、时区 +00:00、隔离级别 REPEATABLE-READ |
| 服务 | app 与 mysql 均 running/healthy |
| HTTP | `/`、`/health/live`、`/health/ready` 均返回 200；未认证 `/admin/auth/session` 返回 401 |
| 初始化 | `pending`，`data_version=0`，覆盖状态 `unknown`；迁移前后数据世代保持不变 |

迁移前员工、部门和门店均为空，同步任务为 2 条。本次未人工触发全量同步、清理业务数据或修改初始化状态。进程运行不代表飞书权限及数据覆盖已验收。

## 恢复边界及未执行项

- 正常应用继续使用兼容 `0008` 的新镜像；不能用旧镜像重新连接当前数据库，也不能通过降级恢复旧会话。
- 如需恢复备份，先停止全部写入方；用具有原 DPAPI 解密能力的 Windows 用户在受限环境解密。核对恢复目标后导入，重新执行当前迁移，再按[部署恢复说明](../deploy/README.md)撤销恢复出的凭据、更新世代，验证后才开放服务。本次没有对真实业务库执行恢复重置。
- 用户确认本轮暂不配置 HTTPS。当前回调为本机 HTTP 地址；正式 HTTPS 登录、刷新、注销及真实企业飞书联调未执行，不能以本轮健康检查代替。
- 镜像构建通过。构建输出另提示前端依赖审计有 2 项 moderate、3 项 high，以及前端产物体积提示；本次未调整依赖版本，也未将这些提示作为数据库迁移验收结果。
