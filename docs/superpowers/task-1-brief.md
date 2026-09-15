# Task 1：后端领域、持久化、接口与权限

**Files:** `backend/pyproject.toml`、`backend/app/`、`backend/migrations/`、`backend/tests/`。

**Interfaces:** 导出 `app.main:app`；环境变量 `ORG_DATABASE_URL`、`ORG_SESSION_SECRET`、`ORG_FEISHU_APP_ID`、`ORG_FEISHU_APP_SECRET`、`ORG_FEISHU_REDIRECT_URI`、`ORG_INITIAL_ADMIN_OPEN_IDS`。HTTP 数据 envelope 为 `{data, meta}`；错误为 `{error:{code,message}}`。管理写入附带 `X-CSRF-Token`。

- [ ] 写领域行为测试：多部门、主部门、嵌套门店、失效、缺失祖先；先执行失败，再实现。
- [ ] 写权限与分页测试：匿名 401、机器凭据不能写管理接口、游标签名及筛选绑定；实现会话和 API 凭据哈希保存。
- [ ] 实现配置、MySQL 模型与 Alembic；读 API、部门/员工/门店查询、批量预览与修改、版本事务、日志、客户端及白名单管理。
- [ ] 实现任务持久提交、复用、重试与状态 API，为 Task 2 保留清晰服务边界。
- [ ] 执行 `python -m pytest backend/tests -q`，保存失败/通过证据与未验证项，输出前端接口说明。

核心行为示例：

```python
# 主部门在总部，兼职大学城店，不能把兼职门店充当主门店。
assert result.store_ids == ["university"]
assert result.primary_store_id is None
assert result.primary_store_status == "not_in_store"
```


## Global Constraints


- 一个实例连接一个飞书组织，使用独立 MySQL；所有业务表使用 InnoDB、utf8mb4。
- 飞书事实只读，本地仅维护门店标记、编码与备注；虚拟根不能设为门店。
- 每条部门关系向上找最近门店；主门店只从唯一飞书主部门派生，未知与不在门店分开。
- 缺页、权限收窄、一次查不到不等于离职或删除；失败保留已提交版本。
- 管理员白名单与只读 API 凭据分开鉴权；秘密不回显、不写日志。
- 事实、派生、日志和版本原子提交；无业务变更不增加版本。
- 跨页/跨端点使用同一世代及版本，变化返回 409，初始化未完成返回 503。
- 中文界面；测试用例围绕行为，真实 MySQL/飞书未验证的项明确保留未验收状态。

