# Task 2 修复轮 1

前端实现代理结束后执行；暂不与其同时实现。

- 逐项修复 task-2-review.md 的 4 个 Important，原 task-2-brief.md 全部约束继续生效。
- 覆盖失效恢复采用受控、可执行并审计的 CLI 或管理员接口，必须保存新验收依据、清除失效 marker、排队全量核对同事务；不能直接把 coverage 改 complete。优先 CLI，避免新增未接通的前端流程；在部署说明/API文档给完整执行方式，不运行真实环境。
- 登录身份首次绑定后不可由 OAuth 覆盖；已存在的三元组不一致拒绝登录。失败记录只含安全错误标识，不记录 code/token/secret；注意抛异常不能把审计一起回滚掉。
- 不把不可读的新部门发布为 active 假事实。推荐保留未解析候选并延后依赖它的新事实；已有记录保留旧事实、降质量。继续满足外键、缺失祖先 unknown、跨范围关系不丢失、不能把关系缺失解释为空。不得通过引入未声明的生命周期绕开现有契约。
- 发布明确 inactive 的员工时原子撤销关联管理员会话；OAuth/会话认证拒绝明确 inactive，pending/unreadable 不是离职。保留或撤销白名单应按现有规格，不把最后管理员当作豁免。测试需覆盖旧会话、新登录与事务失败回滚。
- Minor 1：把安全的固定缺字段错误码纳入稳定映射。Minor 2 的第三方弃用 warning 可以明确记录而不升级整个框架，也不要用宽泛过滤吞掉新的告警。
- 根代理接口回归补充：注入 SQLAlchemy `OperationalError` 到公开读取后，实际返回 `500 text/plain Internal Server Error`，不符合统一 error envelope。为数据库异常增加稳定 JSON 错误（不可用用 503），不要向响应或日志输出 SQL 参数/异常原文；生产 engine 使用 `hide_parameters=True`，添加具体故障注入测试。测试执行过且未连接数据库。
  同时核对框架未知路由的 404/405（Starlette HTTPException），也应保持 JSON error envelope，仍不能回退 HTML。
- 用针对性 RED→GREEN 测试验证修复，再运行覆盖套件与离线迁移；报告追加 task-2-report.md，逐项列测试命令结果。
- 你拥有 backend/**、docs/backend-api.md 和本报告，可补 deploy/README.md 的覆盖重新验收 CLI 文档。不要改 frontend、deploy/*.py 或派生代理。真实 MySQL/飞书仍未提供，不调用。
