# Task 3 修复轮 3

处理 task-3-rereview-2.md 和 root 本轮真实浏览器直接回归。后端停止后才由 root 正式派发；单实现代理。

1. 父子整组一致性：固定 epoch/version 的子请求 409 不要在 readAll 内重复同一个过期基准，立即交给父子协调层重新取父版本。组织、门店都要有整个自动重试周期上限；持续变化时停下来显示错误及手动重试，不能无限循环。手动重试重置预算且重读父子，不发送无版本子请求。追加行为测试覆盖成功恢复和持续冲突后的请求停止。
2. 补齐原修复要求的真实组件测试：OrganizationPage 勾两项、编辑备注、preview/apply409、父列表刷新、第二次提交完整两changes且新version；StoresPage 父子版本协调；手动三级折叠/展开（不能只click节点选择）；日志 UTC 起止时间传参（现有action/source/actor测试保留）。不要通过仅rerender StoreEditor来代替父页面集成行为。
3. 手机选中部门后页面横向溢出：root Edge 390×844，组织页搜索并选择上海静安店，Drawer关闭后等待600ms，document.documentElement.scrollWidth=788。脚本 C:/Users/Vilin/AppData/Local/Temp/org-ui-fixed-check.cjs，截图 qa-fail-mobile-tree.png。修复布局最小宽度、Card标题/操作换行；表格允许自身横向滚动，但整个页面宽度保持390。同时快速核查门店、同步、日志手机宽度，避免同源布局缺陷。
4. 修正已有 useForm 未连接警告（Settings隐藏Tab或StoreEditor关闭时），不要屏蔽console。保持通过的batch409 draft、Tree搜索/clear、source=feishu、每日03:00规则。

验证：前端全套、build、Ant Design lint；可复用本机 Edge Playwright做手机宽度，禁止真实DB/飞书或生产绕过。报告后停止修改，不改后端或派代理。

## 实施期间合并的整体审查发现

- F2：首次 preview 409 也须保留草稿、清旧预览、刷新父版本，下一次以新版本重试；原来仅 apply 分支处理。
- F3：同步事件待处理实际为 queued；覆盖 incomplete 显示“覆盖不完整”；展示 status.meta.last_full_sync_at；详情轮询进入终态后刷新 jobs/status/events，防止成功抽屉与旧摘要矛盾。
- F4：人员详情展示 employee/department 同步质量与 stores.path_names 归属路径；pending_verification 不被绿色 resolved 掩盖。
- M1：日志对象类型使用 admin_allowlist 与实际 membership/security/settings 等类型，避免管理员筛选无结果。

以上已由 final_review 独立确认，合并在本轮完成和验证，不另行并发实现。
