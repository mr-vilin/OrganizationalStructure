# Task 3 整体审查限定修复

等待 root 正式派发（当前后端实施中）。只修 final-review 的 F3 残留、M1 缺项及本轮直接回归，保留 R3 已通过行为。

1. SyncPage 最后成功全量时间的实际来源是 `status.meta.last_full_sync_at`，不是 `status.data.last_full_sync_at`。使用真实 envelope 形状做显示测试。
2. 每次 detail.reload 的 useResource 会先清空 data；当前 effect 把 previousDetailStatus 写成 undefined，随后 succeeded 到达无法识别前一 running，实际不会刷新 jobs/status/events。保留最后非空任务状态、按任务 ID 隔离，在 queued/running → succeeded/failed 时刷新三组摘要；真实 hook 加载空档下验证。不得只mock直接 running→succeeded 从而跳过失败路径。
3. 日志对象筛选还缺 membership，加入实际枚举并复验原 admin_allowlist。

F2 preview409、F4人员质量/路径、queued/incomplete、手机布局、父子版本有界重试均已经通过或由最终审查确认，不另行重写。日志数字cursor由后端当前修复统一为string，不需要改前端。

针对测试先 RED/GREEN；完成前端全套、build、AntD lint。root 负责对应浏览器复验。追加 task-3-report.md，结束后停止，不派代理、不改后端。

root 已准备真实 Edge 脚本 `C:/Users/Vilin/AppData/Local/Temp/org-ui-sync-check.cjs`，用 meta 提供最后成功时间，detail第二次响应延迟150ms模拟loading空档，验证三组摘要重新请求及queued事件。当前已RED：最后成功时间未显示2026，断言失败。根任务将在修复后执行，不需绕过断言。
