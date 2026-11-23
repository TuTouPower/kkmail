---
pid: "p086"
slug: "gmail_virtual_folder_dash_misread_as_syncing"
status: "closed"
resolution: "transferred"
reason: "已核实根因与范围并转交该 task"
fix_ref: "t084"
---
# p086 新加 Gmail 账号后「重要邮件」「所有邮件」永久显示蓝色 "-"，被误读为仍在同步

- 现象：用户新添加 Gmail 账号（截图 2026-11-23，账号 `ecart95tr@gmail.com`），展开账号节点后「重要邮件」「所有邮件」右侧显示蓝色 `-`；用户据此认为这两个目录"同步了这么久还没同步完"。实际这两个目录没有同步任务在跑，且永远不会产出邮件数据，`-` 会永久存在，不会随等待消失。
- 影响：
    1. 新用户把 `-` 当作"同步中/未完成"，等待一个永远不会完成的同步（本次报告即如此），形成重复支持负载。
    2. 「重要邮件」「所有邮件」两个一等导航视图始终为空且无任何说明；用户点进去看不到邮件，也不明白它们被排除在同步之外。
    3. `docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md:72` 把"默认 paused 需手动点进该文件夹触发同步"作为依赖 All Mail 用户的兜底，但 p060 修复后显式 `folder_id` 指向 paused 文件夹解析为空目标集（`src/mail_core/mail/application/sync_requests.py:214-225`），该兜底已失效，UI 也无替代说明——文档承诺与实际行为矛盾。
    4. 已确认同类位点：`role=all` 与 `role=important` 同一代码路径；Gmail 之外任何被置 `paused` 的目录同样产出 `unread_count=null` 并渲染 `-`。非 Gmail 的 `\Noselect` 父目录已被 t052 置 `notSelectable` 不再渲染角标，不属于本修复范围。
- 根因：产品缺陷（UI 状态语义缺失/误导），同步引擎行为本身符合既定设计。
    - 设计既定：`docs/tasks/t056_gmail_sync_strategy_and_timeout/task.md:12,31`（AC-001）要求 Gmail `\All`/`\Important` 默认 `paused` 且不排入抓取队列。`src/mail_core/sync/engine.py:299-327,356` 按 `role in ("all","important")` 或精确 `remote_id` 集合判定虚拟目录，置 `paused` 且 `enqueued=False`，因此永不产出 `FolderStats` 行。
    - `src/mail_core/mail/application/queries.py:219-220` 在无 `FolderStats` 行时返回 `unread_count=None`；`src/frontend/src/components/Sidebar.tsx:342` 把 `null` 渲染为蓝色 `unread-badge-unknown` `-`。
    - 侧栏对"永久暂停/不参与同步"与"统计暂未生成/同步中"使用完全相同的 `-` 角标，`title` 仅为目录名（`Sidebar.tsx:337`），无 tooltip、状态标签或空态文案区分，用户无从判断。
    - `-` 表示"未读数未知"本身符合 `docs/specs/inbox_ui_and_search.md:70` 与 `docs/blueprint/conventions.md:156-159`；缺陷不在于把 `null` 当 0（未发生），而在于 paused 虚拟目录缺少独立、可解释的呈现。
    - 已排除：同步任务积压/卡死、账号认证失败、IMAP 超时。复现显示这两个目录没有任务入队，账号其余目录（如 INBOX）正常入队并生成统计。
- 测试缺口：
    - `tests/mail_core/test_gmail_sync_strategy_and_timeout.py:69-104`（AC-001）只断言后端"虚拟目录 paused 不入队"，未覆盖该状态如何呈现给用户。
    - `src/frontend/src/components/Sidebar.test.tsx` 把 `null → -` 作为正向渲染断言，缺少"`paused` 虚拟目录应显示可解释状态（不参与同步/空态说明）而非裸 `-`"的组件测试。
    - 应补：组件层对 `role=all`/`role=important` 且 `sync_status=paused` 的目录断言不显示裸 `-` 而有区分性标记；契约层确认 `folder-stats` 响应保留 `sync_status` 供前端分支；并更新 t056 风险段与 p060 的兜底描述，消除文档矛盾。
- 线索：`.scratch/repro_gmail_virtual_folder_dash.py`（纯 Python 镜像 `engine.py:309-327,356`、`queries.py:219-220`、`Sidebar.tsx:342` 的决策链；输出：INBOX 入队并出统计，重要/所有邮件 `paused` 不入队 → `null` → 蓝色 `-`）。
- 处理：t084；resolution=transferred；reason=已核实根因与范围并转交该 task
