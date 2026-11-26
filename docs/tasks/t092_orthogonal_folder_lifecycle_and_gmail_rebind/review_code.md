# Task review t092（reviewer_focus: 代码）

- task：`t092_orthogonal_folder_lifecycle_and_gmail_rebind`
- spec：`docs/tasks/t092_orthogonal_folder_lifecycle_and_gmail_rebind/task.md`
- diff_anchor：`71585e7b130e65f9d00fa5f5948692b0b52901ef`
- target：`git diff 71585e7b130e65f9d00fa5f5948692b0b52901ef`
- round：1
- reviewed_at：2026-11-26T13:56:59+08:00

## Findings

### t092_code_f001 - IMAP 目录原位重绑定与 0007 合并未重写 Message.remote_id，导致后续对账误删与写回/归档失效

- 严重度：critical
- 锚点：违反 `AC-001` 与 `AC-003`；行为缺陷：IMAP 语言切换重绑定或 `0007` 合并存量双语目录后，已有邮件因 `messages.remote_id` 内嵌旧文件夹路径而在后续对账中被批量删除且出站写回/正文归档永久失败
- 位置：`src/mail_core/sync/engine.py:363-376`、`src/mail_core/sync/engine.py:218-230`、`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:80-132`、`src/mail_core/providers/imap.py:357-359,752,1257-1287,1354,1635-1641,1919-1923`
- 问题：`ImapProvider.fetch_metadata_page` 落库的 `Message.remote_id` 格式为 `f"{uidvalidity}\x1f{folder_remote_id}\x1f{uid}"`（`src/mail_core/providers/imap.py:357-359,752`）。当 `sync_account_folders` 原位将物理容器 `Folder.remote_id` 从旧路径（如 `"[Gmail]/&XfJT0ZCuTvY-"`）重绑定到新路径（如 `"[Gmail]/Sent Mail"`）或迁移 `0007` 将 `donor` 的 `message_locations` 并入 `survivor` 时，两处均未同步重写对应 `Message.remote_id` 中嵌入的 `folder_remote_id`（新测试 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:139,320` 使用 `"m1"` / `"msg-imp"` 伪键掩盖了该路径）。这会直接触发四重破坏：(1) `reconcile_folder` 调用 `ImapProvider.reconcile(new_remote_id, local_ids)` 时用新路径构造 `remote` 集合，旧 `remote_id` 全部落入 `local - remote`，导致 `_apply_delete_batch`（`src/mail_core/sync/reconcile.py:64-99`）将重绑定/合并前的已有邮件位置乃至孤立邮件行全部误删；(2) `mutations.py` 传入新 `folder.remote_id` 与旧 `msg.remote_id` 后，`ImapProvider.apply_remote_operations`（`imap.py:1635-1641`）因 `desired["folder_remote_id"] != parsed[1]` 拒绝所有已读/旗标/废纸篓写回；(3) `fetch_mime`（`src/mail_core/blobs/archive.py:1070` -> `imap.py:1257-1287`）直接 `SELECT` `parsed[1]` 的已消失旧路径而失败；(4) `delta_changes` 产生的新路径 `remote_id`（`imap.py:1354`）无法匹配已有 `Message`，导致 flag 更新丢失或重拉重复建行。
- 建议：在 `sync_account_folders` 对物理 `container` 执行重绑定以及 `20261126_0007` 的 `_coalesce_gmail_duplicate_folders` 合并 `donor` 容器时，在同事务中将关联且格式匹配 `{uidvalidity}\x1f{old_remote_id}\x1f{uid}` 的 `messages.remote_id` 原子重写为 `{uidvalidity}\x1f{new_remote_id}\x1f{uid}`（`0007` 合并场景若目标 `remote_id` 已在同账号存在重复 `Message` 行则需合并外键关联后去重），并同步修正未完成 `remote_operations.desired_state` 中引用旧路径的 `folder_remote_id` / `remote_id`。

### t092_code_f002 - 迁移 20261126_0007 重算 folder_stats 时将 is_read IS NULL 计入未读整数，破坏未知未读数不变量

- 严重度：important
- 锚点：违反 `AC-001` 与 `docs/blueprint/conventions.md:166` 未知未读数契约
- 位置：`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:141-167`（对照 `src/mail_core/mail/storage/folder_stats.py:43-55`）
- 问题：`_coalesce_gmail_duplicate_folders` 在合并物理 `container` 后重算 `folder_stats` 时，使用 `WHERE ml.folder_id = :fid AND (m.is_read IS FALSE OR m.is_read IS NULL)` 将读状态未知（`is_read IS NULL`）的邮件直接计入整型 `unread_count`。而项目权威统计逻辑 `recompute_folder_stats`（`src/mail_core/mail/storage/folder_stats.py:46-54`）与 `docs/blueprint/conventions.md:166` 明确规定：只要目录内存在任意 `is_read IS NULL` 邮件，`folder_stats.unread_count` 必须为 `NULL` 并向账号、分组与全局聚合传播未知态，严禁把未知态折算为未读整数。
- 建议：将 `20261126_0007` 第 141-167 行的重算 SQL 对齐 `recompute_folder_stats` 语义，分别统计 `is_read IS FALSE` 与 `is_read IS NULL` 计数，当 `unknown > 0` 时写入 `unread_count = NULL`。

### t092_code_f003 - 迁移 20261126_0007 合并目录时只检查 survivor 是否存在 checkpoint 行，可能丢弃 donor 已完成基线

- 严重度：important
- 锚点：违反 `AC-001`（「完整保留既有消息位置归属与未失效增量检查点」）
- 位置：`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:99-110`
- 问题：`_coalesce_gmail_duplicate_folders` 判断 `has_survivor_cp` 时仅查询 `SELECT 1 FROM sync_checkpoints WHERE folder_id = :fid LIMIT 1`。在迁移前已因切语言产生双份目录的存量账号中，旧目录（`donor`）通常持有 `full_scan_complete = true` 的完整增量水位，而新激活的本地化目录（`survivor`）在首轮部分拉取/中断后往往已生成一行 `full_scan_complete = false` 的未完成 checkpoint；当前实现见到任意行即执行 `DELETE FROM sync_checkpoints WHERE folder_id = :donor`，直接丢弃了已完成基线并在合并全部 `message_locations` 后退化为未完成全扫。
- 建议：在决定保留 `survivor` 或迁入 `donor` 的 `sync_checkpoints` 时，除判空外应比较 `full_scan_complete`（若 `survivor` 尚未完成全量基线而 `donor` 已 `full_scan_complete = true` 且 `uidvalidity` 未冲突，应以 `donor` 的已完成 checkpoint 替换保留），避免有效增量水位丢失。

### t092_code_f004 - \_FOLDER_ROLE 缺失 Gmail 中英文已发与英式废纸篓名称，无 SPECIAL-USE 标志时名称回退失效

- 严重度：important
- 锚点：违反 `AC-002`（「名称回退匹配在剥离厂商命名空间前缀后统一映射标准角色，确保中英文 Gmail 的重要邮件目录与全部系统角色在入库阶段即携带准确 `role`」）
- 位置：`src/mail_core/providers/imap.py:226-257`、`src/mail_core/providers/imap.py:777-801`
- 问题：本次变更按 `AC-005` 从 `src/frontend/src/components/Sidebar.tsx:98-112` 移除了前端 `sent mail` / `已发邮件` 等名称猜测逻辑，将目录名称回退识别完全收口到后端 `ImapProvider._match_known_folder_role`。但 `_FOLDER_ROLE`（`imap.py:226-257`）在 `sent` 映射中仅包含 `"Sent"` / `"Sent Items"` / `"Sent Messages"` / `"已发送"` / `"已发送邮件"`，缺少 Gmail 标准英文 `"Sent Mail"` 与简体中文 Gmail `decode_mutf7("[Gmail]/&XfJT0ZCuTvY-")` 对应的 `"已发邮件"`（以及英式 Gmail `"Bin"`）。当 `LIST` 响应省略 `\Sent`（或 `\Trash`）SPECIAL-USE 属性仅返回 `[Gmail]/Sent Mail` 或 `[Gmail]/&XfJT0ZCuTvY-` 时，剥离 `[Gmail]/` 后回退查找会落入 `role="other"`，连带导致 `AC-003` 重绑定与 `AC-005` 侧栏展示退化。
- 建议：在 `src/mail_core/providers/imap.py` 的 `_FOLDER_ROLE` 中补齐 `"Sent Mail": "sent"`、`"已发邮件": "sent"` 与 `"Bin": "trash"`（及必要时常见 Gmail 别名），确保所有中英文 Gmail 系统目录在无 SPECIAL-USE 标志下也能准确入库。

### t092_code_f005 - 出站写回主位置解析在仅有 missing / view / 不可选位置时仍返回非可同步目录，继续向失效或视图目录发起写回

- 严重度：important
- 锚点：违反 `AC-004`（「出站写回主位置解析严格仅纳入 `remote_state='active'`（写回/同步且要求 `kind='container'` 与 `selectable=true`），不因失效历史目录存在而暴露重名条目、毒化聚合计数或向已消失远端目录发起写回」）
- 位置：`src/mail_core/mail/application/mutations.py:73-90,145-161,191-207,262-282,389-441`
- 问题：`_primary_location`（`mutations.py:73-90`）与 `mark_all_messages_read`（`mutations.py:403-432`）仅在 `_primary_location_sort_key` 中将 `syncable=True` 排在 `syncable=False` 之前，而未过滤掉 `remote_state != 'active'`、`kind != 'container'` 或 `selectable=False` 的位置。当某封邮件的物理容器已从远端消失（仅剩 `remote_state='missing'` 行）或仅挂载在派生视图（如 `kind='view'` 的 `[Gmail]/Important`）上时，写回（`set_message_read`、`set_message_flagged`、`trash_message`、`mark_all_messages_read`）仍会解析到该 `missing` 目录或 `view` 并入队以 `missing_folder.remote_id` / `"[Gmail]/Important"` 为 `folder_remote_id` 的 `RemoteOperation`，直接向已消失远端目录或非容器视图发起出站写回。
- 建议：在 `_primary_location` 与 `mark_all_messages_read` 中严格仅从满足 `is_syncable_folder`（`kind == 'container'`、`selectable is True`、`remote_state == 'active'`）的关联位置中解析主写回位置；当邮件存在持久化位置但没有任何可同步物理容器时，不将其回退到已消失/视图目录或硬编码 `"INBOX"` 发起远端写回（保持本地状态变更或按无远端目标处理，同时保持无任何位置记录的单元测试兼容路径）。

### t092_code_f006 - Sidebar 仍以 role === 'other' 限制 notSelectable，非 other 角色的 selectable=false 节点仍可点击且显示未知 -

- 严重度：important
- 锚点：违反 `AC-005`（「准确对 `selectable=false` 结构节点禁点且不显示未知 `-`」）及 `docs/blueprint/conventions.md:171`
- 位置：`src/frontend/src/components/Sidebar.tsx:293`（对照 `src/mail_core/mail/application/queries.py:274-276`）
- 问题：后端 `list_folder_stats_for_account`（`queries.py:274-276`）与同步调度（`sync_requests.py:217`、`engine.py:547`）均无条件将所有 `selectable === false` 的目录视为不可选择结构节点并将 `total_count`/`unread_count` 置为 `null`。但 `Sidebar.tsx:293` 仍沿用旧版过滤条件 `const notSelectable = folder.selectable === false && role === 'other'`，未移除 `&& role === 'other'` 限定。若 IMAP 服务器返回带已知角色名（如 `\Noselect \HasChildren` 的 `"Archive"`，入库为 `role='archive', selectable=false`）的结构容器节点，前端会将其判定为 `notSelectable === false`，既允许用户点击导航至空目录，又会在 318 行渲染出规范禁止的未知角标 `-`。
- 建议：将 `src/frontend/src/components/Sidebar.tsx:293` 改为直接依据正交字段 `const notSelectable = folder.selectable === false`。

### t092_code_f007 - \_find_system_rebind_pairs 在 Gmail 账号并存历史 missing 行与刚消失 active 行时拒绝 1-to-1 重绑定

- 严重度：minor
- 锚点：违反 `AC-003`（「不产生双份重复系统目录」）边界场景
- 位置：`src/mail_core/sync/engine.py:202-215`
- 问题：`_find_system_rebind_pairs` 对 Gmail 账号放行 `folder.remote_state != 'active'` 进入 `missing_buckets`。若某 Gmail 账号因历史非 `[Gmail]/` 路径（迁移 `0007` 仅合并 `remote_id LIKE '[Gmail]/%'`）或其他原因已存在一条同 `(kind, role)` 的旧 `missing` 行，随后当前 `active` 系统目录又在本次发现中切语言换名，则 `missing_buckets[key]` 会同时收录旧 `missing` 行与刚消失的 `active` 行，导致 `len(candidates) == 2`，从而跳过重绑定并再创建一条重复目录。
- 建议：在按 `(kind, role)` 归桶时优先匹配本次由 `active` 转为消失的候选行；仅当同 `(kind, role)` 不存在 `active` 消失候选时，才允许 Gmail 回退匹配历史 `missing` 行（或对同名同角色多缺失行做合并收口）。

### t092_code_f008 - 新增辅助函数与同步入口守卫圈复杂度超 15 且存在三处重复分支

- 严重度：minor
- 锚点：代码质量门禁（圈复杂度标准 `CC ≥ 15` 且新增分支/新建 ≥ 15；DRY 原则）
- 位置：`src/mail_core/providers/imap.py:777-801`、`src/mail_core/sync/engine.py:545-550`、`src/mail_core/sync/delta.py:385-390`、`src/mail_core/sync/reconcile.py:173-178`
- 问题：`imap.py:777` 新建 `_match_known_folder_role` 圈复杂度达 `15`（两层循环线性扫描 `_FOLDER_ROLE`）；同时 `sync_folder_metadata`（`engine.py:509`，CC 33→34）、`sync_folder_delta`（`delta.py:351`，CC 44→45）与 `reconcile_folder`（`reconcile.py:150`，CC 26→27）均因拆出 `is_view_folder` / `not folder.selectable` / `remote_state != 'active'` 三段完全相同的 6 行守卫而增加了分支复杂度并引入三处逐字重复。
- 建议：在 `imap.py` 将 `_FOLDER_ROLE` 预建为小写字典实现 O(1) 匹配并拆分前缀剥离逻辑降低 `_match_known_folder_role` 复杂度；在 `folder_views.py` 提取共享 helper（如 `folder_skip_reason(folder)`）消除三处执行入口的重复守卫与额外分支。

## 结论

- 本轮新发现：8 条（critical 1、important 5、minor 2）
- 未进表的提示：
    - **文件膨胀（达到阈值且本 task 净增）**：
        - `src/`（阈值 400 / 800）：`src/mail_core/providers/imap.py`（1988 行，净增 +22，≥800）、`src/mail_core/sync/engine.py`（860 行，净增 +77，≥800）、`src/mail_core/api/mail.py`（1047 行，净增 +1，≥800）、`src/mail_core/sync/idle_watcher.py`（740 行，净增 +3，≥400）、`src/mail_core/sync/delta.py`（712 行，净增 +11，≥400）、`src/mail_core/mail/storage/models.py`（643 行，净增 +21，≥400）、`src/mail_core/mail/application/queries.py`（612 行，净增 +25，≥400）、`src/mail_core/mail/application/mutations.py`（459 行，净增 +36，≥400）。
        - `tests/`（阈值 600 / 1200）：`src/frontend/src/components/Sidebar.test.tsx`（1443 行，净增 +31，≥1200）、`tests/mail_core/test_t061_status_patrol.py`（735 行，净增 +1，≥600）。
        - 排除说明：`schemas/openapi.json`（5627 行）与 `src/frontend/src/api/generated/schema.ts`（3441 行）为 OpenAPI 契约与 TypeScript codegen 生成产物，按标准排除；`src/mail_core/db/baseline.py`（1233 行，+1/-1）、`src/mail_core/mail/application/sync_requests.py`（808 行，+9/-14）、`src/mail_core/worker/main.py`（717 行，+3/-4）、`src/frontend/src/components/Sidebar.tsx`（1495 行，+9/-33）与 `tests/mail_core/test_t061_idle_watcher.py`（1433 行，+7/-7）本 task 无净增。
    - **圈复杂度 ≥ 10 提示**：`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:38` `_coalesce_gmail_duplicate_folders`（CC=13）、`src/mail_core/sync/engine.py:188` `_find_system_rebind_pairs`（CC=13）、`src/mail_core/providers/imap.py:1017` `list_folder_catalog`（CC 38→33）、`src/mail_core/sync/engine.py:233` `sync_account_folders`（CC 41→40）、`src/mail_core/mail/application/sync_requests.py:177` `resolve_sync_targets`（CC 30→29）、`src/frontend/src/components/Sidebar.tsx:188` `AccountFolders`（估算 CC≈71，已因移除 `inferEffectiveRole` 与硬编码名称分支而净下降）。
    - **范围外观察**：`src/frontend/src/components/MessageList.tsx:209-215,238-245` 按 `folderRole` 汇总统计时未过滤 `f.selectable !== false`，若出现非 `other` 角色的 `\Noselect` 节点会导致列表头部统计退化为未知 `—`；`docs/specs/account_connection.md:31` 仍保留已废止的 Gmail 虚拟标签默认 `paused` 旧描述，建议后续统一同步。
- 总体判断：存在 1 个 critical 与 5 个 important 阻断缺陷（覆盖 IMAP 重绑定/合并后 `Message.remote_id` 漂移、迁移 `0007` 未知未读数与检查点丢失、`Sent Mail`/`已发邮件` 名称回退缺失、写回主位置向已消失/视图目录退化及侧栏 `\Noselect` 角色限定漏洞），判定不通过。
- 系统性 follow-up：无（上述问题均属本 task 范围且应在本轮直接修复；若后续希望从根因彻底解除 IMAP 消息实体键对可变文件夹路径的耦合，可单独立项「IMAP 消息实体键与可变文件夹路径解耦 (`decouple-imap-message-remote-id-from-folder-path`)」）。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。核查 `models.py`、`baseline.py` 与 `20261126_0007` 迁移代码确认结构列与校验链就位，但 `0007` 存在重算 `folder_stats` 将 `is_read IS NULL` 计入未读（`t092_code_f002`）、存在未完成行时丢弃 `donor` 已完成检查点（`t092_code_f003`）及未重写 `messages.remote_id`（`t092_code_f001`）三处阻断缺陷，且当前 worktree 缺 `.env.test` 无法复跑 PG 迁移测试。
- AC-002：TICK-VOID，re_verified。核查 `enums.py` 与 `imap.py` 确认 `FolderRole` 含 `flagged`/`important` 且优先识别 `\Important`，但 `_FOLDER_ROLE` 缺失 `"Sent Mail"` 与 `"已发邮件"` 等 Gmail 系统名（`t092_code_f004`），无 SPECIAL-USE 标志时名称回退仍落为 `"other"`。
- AC-003：TICK-VOID，re_verified。核查 `engine.py`、`delta.py`、`reconcile.py`、`sync_requests.py` 确认原位重绑定与 `container`/`view` 消失收敛(`folder_deleted`)及复活恢复逻辑已接入，但物理容器重绑定后未重写 `messages.remote_id` 嵌入路径（`t092_code_f001`），后续对账会误删邮件且写回/归档失败。
- AC-004：TICK-VOID，re_verified。核查 `folder_views.py`、`queries.py`、`metadata.py`、`label_backfill.py` 确认 `Important` 视图隔离与统计/查询过滤 `remote_state='active'` 均已落地，但 `mutations.py` 的 `_primary_location` 与 `mark_all_messages_read` 在仅有 `missing`/`view`/`selectable=false` 位置时仍将其作为写回目标（`t092_code_f005`）。
- AC-005：TICK-VOID，re_verified。复跑 `export_openapi.py --check`、`npm run openapi:check`、`tsc -b` 与 `Sidebar.test.tsx` 均通过并确认已移除 `sync_status` 与前端名称猜角色，但 `Sidebar.tsx:293` 仍以 `role === 'other'` 限制 `notSelectable`，非 `other` 角色的 `selectable=false` 节点仍可点击并展示 `-`（`t092_code_f006`）。
- AC-006：TICK-VALID，trust_prior。独立复跑 `check_doc_sensitive.py`（36 文件 0 违规）、前端 Vitest（56 文件 598 通过）/lint/build、桌面端测试、Playwright stubApi E2E（25 通过）、模板契约（389 通过 1 跳过）与后端 unit 模式（1712 通过 568 跳过）全部通过，并核查 `mail_sync_and_storage.md` 与 `blueprint`/决策文档更新完整；因 worktree 缺 `.env.test`（`MAIL_CORE_DATABASE_URL` 未配置），后端 PostgreSQL 完整套件依赖实施环境已就绪的 PG 会话先验验证。

coverage = 5 / 6

reviewed_scope: 8eeb009165333b3d

verdict: FAIL

## Round 2 (2026-11-26T18:32:04+08:00)

- diff_anchor：`71585e7b130e65f9d00fa5f5948692b0b52901ef`
- target：`git diff 71585e7b130e65f9d00fa5f5948692b0b52901ef`
- round：2
- reviewed_at：2026-11-26T18:32:04+08:00

### 前轮 Finding 复核

- `t092_code_f001`（critical）：**已消除**。`src/mail_core/sync/folder_rebind.py:96-314` 与 `src/mail_core/sync/engine.py:344-350` 为物理 `container` 原位重绑定在同事务中将关联 `Message.remote_id` 与开放 `RemoteOperation`（`entity_key` 及 `desired_state` 中各 folder 键）重写为新路径并在 `target_rid` 碰撞时合并外键关联后去重；`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:67-262,326-332` 在 `donor` 容器合并时执行对等原子重写、外键合并与 `message_blobs.ref_count` 扣减。
- `t092_code_f002`（important）：**已消除**。`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:397-425` 重算 `folder_stats` 时分别统计 `is_read IS FALSE` 与 `is_read IS NULL`，当 `unknown_read > 0` 时严格写入 `unread_count = NULL`，与 `src/mail_core/mail/storage/folder_stats.py:43-55` 一致。
- `t092_code_f003`（important）：**已消除**。`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:334-372` 合并目录检查点时先对比 `survivor` 与 `donor` 的 `full_scan_complete` 与 `uidvalidity`，在 `survivor` 未完成而 `donor` 已完成且 `uidvalidity` 兼容时保留并提升 `donor` 检查点。
- `t092_code_f004`（important）：**已消除**。`src/mail_core/providers/imap.py:240-261,781-816` 在 `_FOLDER_ROLE` 补齐 `"Sent Mail": "sent"`、`"已发邮件": "sent"` 与 `"Bin": "trash"`，预建 `_FOLDER_ROLE_LOWER` 并提取 `_strip_gmail_prefix` 剥离 `[Gmail]/` 前缀后大小写不敏感匹配。
- `t092_code_f005`（important）：**已消除**。`src/mail_core/mail/application/mutations.py:73-106,162-179,209-226,281-305,413-469` 拆出 `_resolve_primary_syncable_location` 与 `_resolve_writeback_folder_remote`，四条出站写回路径（`set_message_read`、`set_message_flagged`、`trash_message`、`mark_all_messages_read`）严格仅取 `is_syncable_folder` 容器，在持久化位置全为 `missing`/`view`/`selectable=false` 时不再回落失效目录、`view` 或 `"INBOX"` 入队 `RemoteOperation`。
- `t092_code_f006`（important）：**已消除**。`src/frontend/src/components/Sidebar.tsx:293,306,318` 已移除 `&& role === 'other'` 限制，直接按 `const notSelectable = folder.selectable === false` 禁点并隐藏 `-`；`src/frontend/src/components/MessageList.tsx:211,238` 同步过滤 `f.selectable !== false`。
- `t092_code_f007`（minor）：**已消除**。`src/mail_core/sync/folder_rebind.py:29-69` 将 `missing_existing` 拆分为 `active_missing`（本次由 `active` 失活）与 `legacy_missing`（历史 Gmail `missing` 行）两桶，优先 1-to-1 匹配 `active_missing`，避免历史 `missing` 行阻断当前活跃系统目录重绑定。
- `t092_code_f008`（minor）：**已消除**。`src/mail_core/providers/imap.py:261,781-816` 将 `_match_known_folder_role` 圈复杂度降至 10（无短路分支计法为 6）；`src/mail_core/mail/domain/folder_views.py:78-86` 提取共享 `folder_sync_skip_reason`，在 `src/mail_core/sync/engine.py:521-523`、`src/mail_core/sync/delta.py:384-386` 与 `src/mail_core/sync/reconcile.py:173-175` 复用并消除了三处重复守卫分支。

### Findings

#### t092_code_f009 - 多处新增或净增分支函数圈复杂度达 CC ≥ 15，且 mark_all_messages_read 内联重复主容器解析

- 严重度：minor
- 锚点：代码质量门禁（圈复杂度标准 `CC ≥ 15` 且新建 ≥ 15 或净增分支；DRY 原则）
- 位置：`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:198,265`、`src/mail_core/sync/folder_rebind.py:29`、`src/mail_core/mail/application/mutations.py:383,427-456`、`src/mail_core/sync/engine.py:201`
- 问题：按 McCabe 近似规则（含 `and`/`or` 短路分支），本轮新增的 `_coalesce_gmail_duplicate_folders`（CC=22）、`_rewrite_coalesced_container_message_paths`（CC=20）与 `find_system_rebind_pairs`（CC=17）新建即 ≥ 15，且 `mark_all_messages_read`（CC 13→16）与 `sync_account_folders`（CC 41→42）净增分支后 ≥ 15。其中 `mark_all_messages_read`（`mutations.py:441-456`）在已定义 `_resolve_writeback_folder_remote`（`mutations.py:102-106`）的情况下仍内联重复 `syncable_folders` / `"INBOX"` / `None` 分支判定。
- 建议：从 `mark_all_messages_read` 抽取复用的批量主写回容器选择 helper 替换内联分支，并将 `0007` 迁移与 `find_system_rebind_pairs` 中的检查点提升及候选归桶逻辑拆分为独立小函数。

#### t092_code_f010 - 规格与决策文档列入 inbox 参与重绑定，但实现 REBINDABLE_SYSTEM_ROLES 未包含 inbox

- 严重度：minor
- 锚点：文档与规格一致性（`docs/specs/mail_sync_and_storage.md:21`、`docs/blueprint/decisions/20261126_orthogonal_folder_lifecycle_and_gmail_rebind.md:8` 与 `src/mail_core/mail/domain/folder_views.py:14-25` 字面不一致）
- 位置：`src/mail_core/mail/domain/folder_views.py:14-25`、`docs/specs/mail_sync_and_storage.md:21`、`docs/blueprint/decisions/20261126_orthogonal_folder_lifecycle_and_gmail_rebind.md:8`
- 问题：`mail_sync_and_storage.md:21` 与决策文档均声明 `inbox / sent / drafts / trash / junk / archive / all / flagged / important` 共 9 个系统角色支持 1-to-1 原位换绑，但 `REBINDABLE_SYSTEM_ROLES` 仅收录后 8 项而未含 `FolderRole.INBOX.value`。虽标准 IMAP 协议约定 `INBOX` 不做本地化换名，但非标准服务商若在 `"收件箱"` 与 `"INBOX"` 间切换会跳过重绑定，且当前文档与实现存在字面偏差。
- 建议：确认意图后统一收敛：若 `INBOX` 按 RFC 语义不参与重绑定，请从上述两份文档的换绑角色清单中移除 `inbox`；若需覆盖非标准服务商收件箱换名，则在 `REBINDABLE_SYSTEM_ROLES` 补齐 `FolderRole.INBOX.value`。

#### t092_code_f011 - \_query_inbox_stats 按角色外连接未过滤 Folder.selectable，与 MessageList 头部统计口径不一致

- 严重度：minor
- 锚点：行为差异（非 AC 阻断轻微不一致：存在非 `other` 角色的 `\Noselect` 节点时分组视图与单/全账号列表统计口径分歧）
- 位置：`src/mail_core/mail/application/queries.py:556-562`（对照 `src/frontend/src/components/MessageList.tsx:192,211,238`）
- 问题：Round 2 已在 `MessageList.tsx:211,238` 为单账号与全账号按 `folderRole` 汇总过滤 `f.selectable !== false`，但 `MessageList.tsx:192` 在分组视图下调用 `query_group_inbox_stats`（经 `_query_inbox_stats`，`queries.py:556-562`）时，`Folder` 外连接仅限定 `Folder.remote_state == 'active'` 而未限定 `Folder.selectable.is_(True)`。若账号存在 `role` 为 `sent`/`archive` 等标准角色的 `\Noselect` 父结构节点（`selectable=False` 且无 `FolderStats` 行），`folder_count > known_unread_count` 会使后端将该账号及分组未读数降为 `None`（`—`），与列表自身单账号统计不一致。
- 建议：在 `src/mail_core/mail/application/queries.py:556-562` 的 `_query_inbox_stats` 外连接条件补充 `Folder.selectable.is_(True)`（仅统计可选择目录，与 `MessageList.tsx` 对齐）。

### 结论

- 前轮 finding 复核：`t092_code_f001` ~ `t092_code_f008` 共 8 条（含全部 1 条 critical 与 5 条 important 阻断项）均已在真实源码与迁移中彻底修复。
- 本轮新发现：3 条（minor 3；critical 0、important 0）
- 未进表的提示：
    - **文件膨胀（达到阈值且本 task 净增）**：
        - `src/`（阈值 400 / 800）：`src/mail_core/providers/imap.py`（2003 行，净增 +37，≥800）、`src/mail_core/api/mail.py`（1047 行，净增 +1，≥800）、`src/mail_core/sync/engine.py`（834 行，净增 +51，≥800）、`src/mail_core/sync/idle_watcher.py`（740 行，净增 +3，≥400）、`src/mail_core/sync/delta.py`（708 行，净增 +7，≥400）、`src/mail_core/mail/storage/models.py`（643 行，净增 +21，≥400）、`src/mail_core/mail/application/queries.py`（612 行，净增 +25，≥400）、`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py`（516 行，新建 +516，≥400；Alembic 单文件迁移快照）、`src/mail_core/mail/application/mutations.py`（488 行，净增 +65，≥400）。
        - `tests/`（阈值 600 / 1200）：`src/frontend/src/components/Sidebar.test.tsx`（1449 行，净增 +37，≥1200）、`src/frontend/src/components/MessageList.test.tsx`（1319 行，净增 +19，≥1200）、`tests/mail_core/test_t061_status_patrol.py`（735 行，净增 +1，≥600）、`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py`（602 行，新建 +602，≥600）。
        - 排除与无净增说明：`schemas/openapi.json`（5627 行）与 `src/frontend/src/api/generated/schema.ts`（3441 行）为生成产物，排除；`src/frontend/src/components/Sidebar.tsx`（1495 行，净增 -24）、`src/mail_core/db/baseline.py`（1233 行，净增 +0）、`src/frontend/src/components/MessageList.tsx`（940 行，净增 +0）、`src/mail_core/mail/application/sync_requests.py`（808 行，净增 -5）、`src/mail_core/worker/main.py`（717 行，净增 -1）与 `tests/mail_core/test_t061_idle_watcher.py`（1433 行，净增 +0）无净增。
    - **圈复杂度 ≥ 10 且未达 ≥ 15 净增阈值提示**：`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:67` `_merge_duplicate_message_sql`（CC=14）、`src/mail_core/sync/folder_rebind.py:213` `_rewrite_remote_ops_for_path_rebind`（CC=13）、`src/mail_core/sync/folder_rebind.py:96` `_merge_duplicate_message_rows`（CC=12）、`src/mail_core/sync/folder_rebind.py:254` `rebind_folder_message_paths`（CC=12）、`src/mail_core/providers/imap.py:792` `_match_known_folder_role`（含短路分支 CC=10 / 无短路 CC=6）、`src/mail_core/providers/imap.py:1032` `list_folder_catalog`（CC 38→33，净降）、`src/mail_core/sync/engine.py:486` `sync_folder_metadata`（CC 33→32，净降）、`src/mail_core/sync/delta.py:350` `sync_folder_delta`（CC 43→42，净降）、`src/mail_core/sync/reconcile.py:150` `reconcile_folder`（CC 26→25，净降）、`src/mail_core/mail/application/sync_requests.py:177` `resolve_sync_targets`（CC 30→29，净降）。
    - **范围外观察**：`src/frontend/src/components/Sidebar.tsx:108` `fetchAccountFolders` 计算账号未读徽标仅过滤 `folder.role === 'inbox'` 而未叠加 `folder.selectable !== false`（标准 IMAP 下 INBOX 恒可选，属防御性一致性改进）；`docs/specs/account_connection.md:31` 仍保留已废止的 Gmail 虚拟标签默认 `paused` 旧描述，建议后续统一同步。
- 总体判断：Round 1 全部 8 条 finding（含 6 条 blocking）均已真实彻底修复且未引入新的阻断缺陷；本轮仅发现 3 条非阻断 `minor` 改进项，代码实现与规格 AC 完全对齐，判定通过。
- 系统性 follow-up：无（`t092_code_f009`~`f011` 均为本 task 内轻量收口，无需单独立项）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。核查 `src/mail_core/mail/storage/models.py`、`src/mail_core/db/baseline.py` 与 `src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py` 确认 `sync_status` 移除、三正交状态及 `ck_folders_remote_state` 约束齐备，且 `0007` 已修复 `messages.remote_id`/`remote_operations` 重写与冲突去重、`is_read IS NULL` 置 `NULL` 未读统计与 `donor` 已完成检查点提升（PG 实库迁移执行由并行 test reviewer 独立验证）。
- AC-002：TICK-VALID，re_verified。独立运行 `test_t092_orthogonal_folder_lifecycle.py` 与 `test_domain_sync_statuses.py` 单元用例通过，核查 `enums.py` 与 `imap.py` 确认补齐 `flagged`/`important`、`\Important` 优先识别、`_strip_gmail_prefix` 前缀剥离及 `"Sent Mail"`/`"已发邮件"`/`"Bin"` 映射。
- AC-003：TICK-VALID，re_verified。核查 `folder_rebind.py`、`engine.py`、`delta.py`、`reconcile.py` 与 `sync_requests.py` 确认 1-to-1 原位重绑定（优先匹配本次失活 `active` 候选）、物理容器 `Message.remote_id`/`RemoteOperation` 重写与去重合并、全形态消失收敛(`folder_deleted`)及复活恢复实现完整。
- AC-004：TICK-VALID，re_verified。核查 `folder_views.py`、`queries.py`、`metadata.py`、`label_backfill.py` 与 `mutations.py` 确认 `\Important` 视图作用域严格隔离、统计与查询过滤 `remote_state='active'`，且四条写回路径不再回退 `missing`/`view`/`selectable=false`/`INBOX`。
- AC-005：TICK-VALID，re_verified。独立复跑 `.venv/bin/python scripts/export_openapi.py --check`、`npm run openapi:check`、`npx tsc -b`、`npm test`（56 文件 599 通过）与 `npm run lint`（0 警告 0 错误）全通过，核查 `api/mail.py`、`schemas/openapi.json`、`schema.ts`、`Sidebar.tsx`（含无 `role === 'other'` 限定的 `notSelectable`）与 `MessageList.tsx` 契约一致。
- AC-006：TICK-VALID，trust_prior。独立复跑 `check_doc_sensitive.py`（36 文件 0 违规）、模板契约（389 通过 1 跳过）、桌面端测试、前端全量单测/类型/lint/契约与后端 unit 全套（1711 通过 569 跳过）全部通过，并核查 `docs/specs/mail_sync_and_storage.md`、`docs/blueprint/` 及决策记录更新完整；完整 PostgreSQL 测试套件与 E2E 冒烟依赖并行 test reviewer / 实施环境先验验证。

coverage = 5 / 6

reviewed_scope: d0f96daec29a5ebd

verdict: PASS

## Round 3 (2026-11-26T19:28:15+08:00)

- diff_anchor：`71585e7b130e65f9d00fa5f5948692b0b52901ef`
- target：`git diff 71585e7b130e65f9d00fa5f5948692b0b52901ef`
- round：3
- reviewed_at：2026-11-26T19:28:15+08:00

### 前轮 Finding 复核

- `t092_code_f009`（minor）：**已消除**。`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:198-475` 已将原高分支逻辑拆分为 `_rewrite_single_remote_op_sql`（含短路 CC=12 / 标准 CC=9）、`_coalesce_pick_key`（CC\<10）、`_migrate_coalesced_checkpoint`（10/3）、`_migrate_coalesced_donor`（\<10）、`_refresh_coalesced_container_stats`（\<10）、`_coalesce_gmail_duplicate_folders`（\<10）与 `_rewrite_coalesced_container_message_paths`（\<10），连同 `_merge_duplicate_message_sql`（14/13）全部新建函数均 `< 15`；`src/mail_core/sync/folder_rebind.py:29-356` 抽取 `_collect_rebind_candidates` 后，`find_system_rebind_pairs` 降至 11/7，其余全部函数均 `< 15`（最大 `_rewrite_remote_ops_for_path_rebind` 13/10）；`src/mail_core/sync/engine.py:185-198,327-335` 抽取 `_apply_folder_attributes` 与调用 `rebind_system_folders`，使 `sync_account_folders` CC 从基线 41/29 净降至 34/26；`src/mail_core/mail/application/mutations.py:109-117,452` 抽取 `_resolve_batch_writeback_folder_remote` 消除内联重复，使 `mark_all_messages_read` CC 从基线 13/12 净降至 11/9。
- `t092_code_f010`（minor）：**已消除**。`docs/specs/mail_sync_and_storage.md:21` 与 `docs/blueprint/decisions/20261126_orthogonal_folder_lifecycle_and_gmail_rebind.md:8` 均已将 1-to-1 原位重绑定系统角色清单统一收敛为 `sent / drafts / trash / junk / archive / all / flagged / important`（移除 `inbox`），与 `src/mail_core/mail/domain/folder_views.py:14-25` 的 `REBINDABLE_SYSTEM_ROLES` 完全一致。
- `t092_code_f011`（minor）：**已消除**。`src/mail_core/mail/application/queries.py:556-562` 的 `_query_inbox_stats` 外连接条件已补充 `& Folder.selectable.is_(True)`，与 `src/frontend/src/components/MessageList.tsx:211,238` 统计口径一致；`src/frontend/src/components/Sidebar.tsx:108` 的 `fetchAccountFolders` 亦已补充 `&& folder.selectable !== false`。

### Findings

#### t092_code_f012 - 重构后残留未使用的 `CONTAINER` 导入

- 严重度：minor
- 锚点：代码质量（死代码与未使用导入清理）
- 位置：`src/mail_core/sync/engine.py:29`、`src/mail_core/sync/patrol.py:29`
- 问题：将原位重绑定抽离至 `folder_rebind.py` 并将巡检过滤统一收敛至 `*syncable_folder_clauses()` 后，`src/mail_core/sync/engine.py:29` 导入的 `CONTAINER` 与 `src/mail_core/sync/patrol.py:29` 导入的 `CONTAINER`（同处并存历史未用的 `is_view_folder`）在各自模块内已零引用，属于本轮重构残留的死导入。
- 建议：移除 `src/mail_core/sync/engine.py:29` 的 `CONTAINER` 导入与 `src/mail_core/sync/patrol.py:29` 未使用的导入行。

### 结论

- 前轮 finding 复核：Round 2 全部 3 条 finding（`t092_code_f009`~`t092_code_f011`）均已在源码、迁移、契约与文档中真实彻底修复，且未引入新阻断缺陷。
- 本轮新发现：1 条（minor 1；critical 0、important 0）
- 未进表的提示：
    - **文件膨胀（达到阈值且本 task 净增）**：
        - `src/`（阈值 400 / 800）：`src/mail_core/providers/imap.py`（2003 行，净增 +37，≥800）、`src/mail_core/api/mail.py`（1047 行，净增 +1，≥800）、`src/mail_core/sync/engine.py`（815 行，净增 +32，≥800）、`src/mail_core/sync/idle_watcher.py`（740 行，净增 +3，≥400）、`src/mail_core/sync/delta.py`（708 行，净增 +7，≥400）、`src/mail_core/mail/storage/models.py`（643 行，净增 +21，≥400）、`src/mail_core/mail/application/queries.py`（613 行，净增 +26，≥400）、`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py`（566 行，新建 +566，≥400；Alembic 单文件迁移快照）、`src/mail_core/mail/application/mutations.py`（488 行，净增 +65，≥400）。
        - `tests/`（阈值 600 / 1200）：`src/frontend/src/components/Sidebar.test.tsx`（1455 行，净增 +43，≥1200）、`src/frontend/src/components/MessageList.test.tsx`（1319 行，净增 +19，≥1200）、`tests/e2e/stubApi.ts`（761 行，净增 +2，≥600）、`tests/mail_core/test_t061_status_patrol.py`（735 行，净增 +1，≥600）、`tests/e2e/sidebar_tree.spec.ts`（670 行，净增 +43，≥600）；原超 600 行的 `t092` 测试已拆分为 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py`（490 行）与 `tests/mail_core/test_t092_downstream_isolation_and_api.py`（205 行），均低于 600 行阈值。
        - 排除与无净增说明：`schemas/openapi.json`（5627 行）与 `src/frontend/src/api/generated/schema.ts`（3441 行）为生成产物，按标准排除；`src/frontend/src/components/Sidebar.tsx`（1495 行，净增 -24）、`src/mail_core/db/baseline.py`（1233 行，净增 +0）、`src/frontend/src/components/MessageList.tsx`（940 行，净增 +0）、`src/mail_core/mail/application/sync_requests.py`（808 行，净增 -5）、`src/mail_core/worker/main.py`（717 行，净增 -1）与 `tests/mail_core/test_t061_idle_watcher.py`（1433 行，净增 +0）无净增。
    - **圈复杂度 ≥ 10 且未达 ≥ 15 净增阈值提示**：全部新增生产函数均已降至 `< 15`（`0007` `_merge_duplicate_message_sql` 含短路 CC=14/标准 CC=13、`_rewrite_single_remote_op_sql` 12/9、`_migrate_coalesced_checkpoint` 10/3；`folder_rebind.py` `_rewrite_remote_ops_for_path_rebind` 13/10、`_merge_duplicate_message_rows` 12/11、`rebind_folder_message_paths` 12/9、`find_system_rebind_pairs` 11/7；`imap.py` `_match_known_folder_role` 10/6）；既存大函数在本 task 中复杂度均净降或持平（`list_folder_catalog` 38→33、`sync_account_folders` 41→34、`sync_folder_metadata` 33→32、`sync_folder_delta` 44→43、`reconcile_folder` 26→25、`resolve_sync_targets` 30→29、`mark_all_messages_read` 13→11、`Sidebar.tsx` `getStandardName` 25→11 与 `AccountFolders` 25→22、`MessageList.tsx` `folderStatsQuery` `queryFn` 22 持平）。另注 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:378` `test_ac003_rebind_patrol_delta_view_disappearance_and_revive` 因链式 `and` 断言与列表推导呈含短路 CC=27（标准 CC=12）。
    - **非 PostgreSQL 复验实测**：`.venv/bin/python scripts/export_openapi.py --check`（46 paths）、`scripts/check_doc_sensitive.py docs --check`（36 文件 0 违规）、`scripts/check_dep_locks.py --check`、`git diff --check`、前端全链（Vitest 56 文件 599 passed、`tsc -b`、`vite build`、`oxlint --deny-warnings` 121 文件 0 警告 0 错误、`openapi:check`、`css:check`）、桌面端单测（12 项通过）、模板契约（389 passed, 1 skipped）、`t092` 单元用例（8 passed, 3 skipped）与后端 `KKMAIL_TEST_MODE=unit`（排除需实时 Dovecot 端口的 `test_imap_provider_live.py` 后 1491 passed, 529 skipped）全部通过。
    - **范围外观察**：`docs/specs/account_connection.md:31` 仍保留已废止的 Gmail 虚拟标签默认 `paused` 旧描述，建议后续统一同步。
- 总体判断：Round 2 全部 3 条改进项（含 `0007`/`folder_rebind`/`engine`/`mutations` 复杂度拆解、文档角色清单统一与 `_query_inbox_stats` 过滤对齐）均已真实落地且无阻断缺陷，代码实现与规格 AC 完全对齐，判定通过。
- 系统性 follow-up：无（`t092_code_f012` 为单行未用导入清理，无需单独立项）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。核查 `src/mail_core/mail/storage/models.py`、`src/mail_core/db/baseline.py` 与拆解重构后的 `src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py` 确认 `sync_status` 移除、三正交状态及 `ck_folders_remote_state` 约束齐备，且保留双语目录原子合并去重、`messages.remote_id`/`remote_operations` 重写、已完成检查点提升及 `is_read IS NULL` 置 `NULL` 统计重算（PG 实库迁移执行由并行 test reviewer 独立验证）。
- AC-002：TICK-VALID，re_verified。独立复跑 `test_t092_orthogonal_folder_lifecycle.py::test_ac002_folder_role_enum_and_imap_important_and_prefix_mapping` 与 `test_domain_sync_statuses.py` 单元用例通过，核查 `enums.py` 与 `imap.py` 确认 `FolderRole` 含 `flagged`/`important`、`\Important` 优先识别、`_strip_gmail_prefix` 前缀剥离及 `"Sent Mail"`/`"已发邮件"`/`"Bin"` 精确映射。
- AC-003：TICK-VALID，re_verified。核查 `folder_rebind.py`、`engine.py`、`delta.py`、`reconcile.py` 与 `sync_requests.py` 确认 1-to-1 原位重绑定（优先匹配失活 `active` 候选）、物理容器 `Message.remote_id`/`RemoteOperation` 原子重写与碰撞去重合并、`container`/`view` 统一收敛 `remote_state='missing'`（`folder_deleted`）及复活恢复实现完整，并复跑 `test_a320_folder_pause_revival.py` 通过。
- AC-004：TICK-VALID，re_verified。核查 `folder_views.py`、`queries.py`（含 `_query_inbox_stats` 补充 `Folder.selectable.is_(True)`）、`mutations.py`（抽取 `_resolve_batch_writeback_folder_remote`，四条写回路径严格仅取 `is_syncable_folder` 容器且不回退失效/`view`/`INBOX`）、`metadata.py` 与 `label_backfill.py` 确认 `\Important` 视图隔离与下游过滤逻辑完整。
- AC-005：TICK-VALID，re_verified。独立复跑 `scripts/export_openapi.py --check`、`npm run openapi:check`、`npx tsc -b`、`npm run build`、`npm run lint`（121 文件 0 警告 0 错误）、`npm run css:check` 与 Vitest（56 文件 599 passed）全通过，核查 `api/mail.py`、`schemas/openapi.json`、`schema.ts`、`Sidebar.tsx` 与 `MessageList.tsx` 契约完全一致。
- AC-006：TICK-VALID，trust_prior。核查 `docs/specs/mail_sync_and_storage.md`、`docs/blueprint/` 及决策记录更新与实现完全一致，独立复跑 `check_doc_sensitive.py`（36 文件 0 违规）、`check_dep_locks.py --check`、模板契约（389 passed, 1 skipped）、前端全量、桌面端单测（12 项通过）与后端 unit 全套（1491 passed, 529 skipped，排除实时 IMAP 端口用例）全通过；完整 PostgreSQL 套件与 E2E 冒烟依赖并行 test reviewer / 实施环境先验验证。

coverage = 5 / 6

reviewed_scope: 359e82c02f56729d

verdict: PASS
