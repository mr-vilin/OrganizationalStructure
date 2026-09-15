# Task 3 修复轮 2

仅修复 task-3-rereview.md 未关闭问题和 R1 直接回归。原规格不变。必须完成后再报告，不在中途结束。

1. **409 保留输入**：真实 OrganizationPage -> 勾选两个部门 -> 修改备注 -> preview/apply 409 -> 父列表 reload，现把备注覆盖回原值。根浏览器已复现。不要在父资源暂时清空或新数组引用出现时重新初始化已打开的编辑草稿；用稳定的编辑会话/选择快照保存草稿，元数据版本单独更新。StoreEditor 独立 rerender 相同数组的测试不能证明此流程；新增父页面集成测试，验证重新预览用新版本且仍提交修改后的备注、完整两个 changes。
2. **父子一致版本**：子资源 409 时不能用旧父版本重复重试；重读父与子整组，有限重试避免循环。在父 meta 未就绪时暂停子请求，不得发送不带 epoch/version 的临时请求。组织和门店两页都处理。覆盖服务器先返回409后父version增加的测试。
3. **树手动展开**：当前无搜索时仍显式传 expandedKeys=undefined，导致树受控但没有 onExpand 更新，点击展开无效，根浏览器在桌面和手机均复现。建立实际受控展开状态，或确实不传受控属性；测试不搜索时手动展开三级节点，以及搜索保留祖先/展开/清除后可继续操作。
4. **日志过滤**：飞书来源值使用 feishu（后端实际写入值），不是 sync；操作/操作者/UTC起止/重置做真实组件请求测试。不得只测 query helper。
5. **现有通过项保持**：浏览器已验证 schedule 保存 03:00 与 Asia/Shanghai、员工真实 shape、手机通过搜索选择后关闭 Drawer。保留这些行为。设置页首次加载有 useForm 未挂载 warning，可通过正确表单挂载时机消除；不得泛化过滤 console。
6. **恢复文档 R1 直接缺口**：deploy/README.md 的 Bash 块需要失败即停止（set -euo pipefail），并在已确认目标库且现状备份成功后清空/重建该目标库再导入；否则旧 schema 备份恢复会残留新版表，后续 Alembic CREATE 冲突。只写明确目标 organization 的文档，不执行。覆盖恢复操作的步骤须明确标注。不要动后端刚补的覆盖重新验收 CLI/七类事件文档。

验证：针对测试先RED后GREEN；完整前端 test/build/antd lint，追加 task-3-report.md 每项映射与命令结果。浏览器失败夹具 `C:/Users/Vilin/AppData/Local/Temp/org-ui-fixed-check.cjs` 供参考，root随后复验。不能把测试夹具当真实MySQL/飞书联调。你拥有frontend/**、前端指南/报告与上述部署文档小段；不改backend、不派生代理。
