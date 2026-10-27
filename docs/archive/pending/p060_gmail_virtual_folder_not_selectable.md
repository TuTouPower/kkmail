# p060 Gmail 虚拟文件夹（重要/所有邮件）导航同步报 folder_not_selectable

- 现象：桌面/Web 界面选中 Gmail 账号的虚拟文件夹「重要邮件」后，邮件列表顶部红字显示原始错误码 `folder_not_selectable`；列表本身正常加载（标题区显示总数/未读，条目可见）。手动刷新同一视图同样报错。用户截图 2026-10-27（账号 xiaoxiaoguang2000@gmail.com）。
- 影响：所有 Gmail 账号的 `role=all`（所有邮件）与 `role=important`（重要邮件）两个一等导航视图每次进入/聚焦/手动刷新都会触发一次必然失败的同步请求并在列表区显示错误码；非 Gmail 的 `\Noselect` 父目录若被导航到同理。邮件数据本身不受影响（虚拟文件夹内容由其他文件夹同步带入，列表查询不依赖该请求）。
- 根因：产品缺陷（后端请求解析层与既定跳过语义不一致）。
    - 设计既定：Gmail `\All` / `\Important` 虚拟汇总标签在文件夹发现时默认置 `sync_status="paused"`，避免全量重复拉取（spec AC-T56-001；`docs/blueprint/architecture.md` IMAP 适配器条；`src/mail_core/sync/engine.py:341-373` 的 `is_gmail_virtual` 判定与赋值）；`\Noselect` 结构节点同为 `paused`（AC-034；`docs/blueprint/conventions.md`：不得为其排任务，旧任务以 skipped 完成）。
    - 执行层对 `paused` 一律宽容跳过：`src/mail_core/sync/delta.py:353`、`src/mail_core/sync/engine.py:475`、`src/mail_core/sync/reconcile.py:122` 均返回 `{"status": "skipped", "reason": "folder_not_selectable"}`；按角色的自动范围解析也在 `src/mail_core/mail/application/sync_requests.py:214` 静默排除 `paused`。
    - 唯一硬失败点：同一文件显式 `folder_id` 分支 `sync_requests.py:196-197` 对 `paused` 文件夹抛 `ValueError("folder_not_selectable")`，经 `src/mail_core/api/mail.py:714-715` 映射为 HTTP 422。
    - 前端进入文件夹视图时由 `src/frontend/src/hooks/use_scope_sync.ts` 的导航/聚焦自动触发以显式 `folder_id` 提交 `POST /api/mail/sync/delta`（作用域组装见 `src/frontend/src/lib/sync_scope.ts` 的 folder 分支），失败后 `errorMessage()` 把后端原始错误码原样存为该作用域错误，`MessageList` 以红字呈现（`scopeSyncError`）。
    - 同类位点（已确认）：`role=all` 视图与 `role=important` 视图同一代码路径；`\Noselect` 父目录文件夹行同理。已扫无其他硬失败点：全仓 `folder_not_selectable` 抛出点仅 `sync_requests.py:197` 一处，其余均为 skipped 返回。
- 测试缺口：现有测试无一条覆盖「显式 `folder_id` 指向 `paused` 文件夹」的解析行为（`tests/mail_core/` 全文无 `folder_not_selectable` 断言）；PG 门控的 `test_sync_requests.py` 只测正常文件夹。应在应用层单元测试补：显式 `folder_id=paused` 返回空目标集（与角色解析一致）、正常文件夹仍返回单目标、已删除/跨账号文件夹仍 404；API 层补一条 delta 请求对 `paused` 文件夹返回 200 且 `target_count=0` 的断言（或在应用层等价覆盖）。
- 线索：`.scratch/repro_folder_not_selectable.py`（SQLite 最小复现：显式 `folder_id` 对 `paused` 的 important 文件夹抛 `ValueError(folder_not_selectable)`；角色范围静默 0 目标；账号范围正常）。
- 处理：fix/folder-not-selectable
