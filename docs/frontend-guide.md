# 管理端使用与启动指南

## 本地启动

1. 当前工作区已准备依赖，可在根目录终端启动后端（默认 `http://127.0.0.1:8000`）：

   ```powershell
   backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
   ```
2. 在仓库根目录运行：

   ```powershell
   npm.cmd --prefix frontend run dev
   ```

3. 打开终端显示的 Vite 地址（默认 `http://127.0.0.1:5173`，占用时会顺延端口）。Vite 会把 `/admin`、`/api`、`/health` 代理给本地后端。
4. 未登录时页面只显示飞书登录入口；身份配置缺失、无权限和后端不可用均有独立提示及重试入口。

管理端默认使用真实接口，不自动登录，也不填充示例业务数据。浏览器请求携带会话 Cookie；写请求在会话验证成功后自动带 `X-CSRF-Token`。

无数据库/飞书配置时，上述命令用于检查服务入口和登录门禁。完整业务联调按[部署说明](../deploy/README.md)配置 MySQL、HTTPS 与飞书；本地 Python 从进程环境变量读取配置，复制 `.env` 本身不会自动加载，Compose 会通过 `env_file` 注入。

## 页面说明

- **组织架构**：一次读取完整且版本一致的部门树；搜索部门，独立勾选节点，按直属或全部后代查看员工。编辑门店资料必须先预览，只有预览内容与当前表单、数据版本都一致时才能提交；遇到 409 会保留表单并要求重新预览。
- **人员详情**：展示全部部门关系、全部门店、唯一主门店和派生状态。“不在门店”与“暂无法判断”分别展示。
- **门店管理**：按名称或编码搜索，切换是否包含失效门店，查看全部归属或主门店归属员工，编辑门店编码和备注。人数栏仅表示该门店归属人数。
- **同步中心**：展示初始化、覆盖、最近全量成功时间、全部任务页、实际阶段与计数。总量未知时显示“总量待确认”，不展示伪百分比。活动任务详情每 3 秒轮询，失败任务可重试。
- **变更日志**：按对象、来源、操作者、任务和时间筛选，抽屉内对照 before/after。
- **管理设置**：维护管理员白名单和只读 API 客户端。客户端创建与轮换的密钥只显示一次；轮换、撤销和移出管理员均要求确认。

## 构建与检查

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
& .tools/antd/node_modules/.bin/antd.cmd lint frontend/src --format json
```

## 连接与计划

同步中心通过 `/admin/api/status` 显示脱敏连接摘要、最近事件处理时间和失败事件数，并可从事件列表重试包含对象 ID 的失败事件。管理设置通过 `/admin/api/settings/reconcile-schedule` 读取和保存每日核对时间，固定使用 `Asia/Shanghai`。
