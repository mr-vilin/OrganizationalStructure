# Task 3 修复轮 1

在 Task 2 实现结束后执行。原规格仍见 task-3-brief.md。

1. 逐项修复 task-3-review.md 中所有 Important；Minor 一并修复（静态 message 改 App.useApp，补 /auth 代理）。不删掉已要求的批量设置功能。
2. 依据最终 docs/backend-api.md 与后端路由/序列化建立精确 TypeScript 类型，不猜测不存在的字段。接通连接摘要、最近事件与每日核对 GET/PUT，移除“后端暂未提供”占位页。主门店、初始化、覆盖、任务阶段/类型/状态用中文表达。
   同步中心接通新增 `GET /admin/api/sync/events` 与 `POST /admin/api/sync/events/{event_id}/retry`，以实际契约展示失败事件和错误并可重试；缺少对象 ID 等不可重试的失败应明确解释，不能伪装提交成功。
3. 修复门店批量预览/确认可达路径；保留每个部门原编码和备注。明确取消/返回编辑行为，提交只用确认的规范化 changes，遇 409 刷新基准版本并保留用户修改，然后可重新预览，不能无限重复提交旧 version。
4. 日志筛选使用新约定 action/actor/committed_after/committed_before，起止时间转 UTC ISO；表单应有重置。跨端点员工请求绑定父 meta，冲突重读父与子，防止各自成功但混版本。
5. 树搜索保留祖先并展开命中节点，独立勾选真实全量提交；窄屏部门树 Drawer，选择后关闭且保留状态。全局鉴权失败清 CSRF/敏感页面并回到门禁。
   组织页为选中部门提供“更新此部门及后代”，提交已有同步任务接口 `{type:'subtree',root_department_id:选中ID}`，显示创建/复用结果并能查看任务；门店标记禁用采用后端 `is_virtual_root`，不要猜硬编码 `root`。
6. 对 StoreEditor 批量完整链、冲突重预览、权限失效、后端真实 shape、日志过滤和树搜索写有意义交互测试。不要仅测试同名纯函数。用具体测试先复现问题再修复；测试数量不是目标。
7. 整理改动页的多行格式，便于后续维护。修复 AntD 6 明确弃用参数（Alert title、Drawer size 等），重新执行测试、build、antd lint。
8. 根代理已有 Playwright 和系统 Edge 可用，`node .../.tools/browser/node_modules/playwright`；系统临时目录 `org-ui-check.cjs` 和 `org-pages-check.cjs` 为首轮失败夹具，不是生产数据。浏览器验证由根代理对修复代码执行，最终报告需补证据。

可同时修复 Task 4 文档缺口：仅 deploy/README.md 补完整的 Bash 恢复导入顺序（停应用、确认目标、先备份、导入 mysql、迁移、新世代、重启核对），不运行恢复。不要把未执行 MySQL/镜像的测试改写成通过。其余 Task4最终台账与验证由根代理完成。

报告追加到 task-3-report.md，写逐项映射与覆盖测试命令/结果。不得派生代理。不要修改 backend。
