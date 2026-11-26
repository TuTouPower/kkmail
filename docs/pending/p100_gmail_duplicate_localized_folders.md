---
pid: "p100"
slug: "gmail_duplicate_localized_folders"
status: "closed"
resolution: "transferred"
reason: "已按开发铁律核实目录正交状态模型、IMAP角色收口、系统目录同实体重绑定合并与历史清洗范围并转交 t092"
fix_ref: "t092"
---
# p100 Gmail 语言切换出现中英双份系统目录且 Important 视图角色断裂

- 现象：生产 Gmail 账号 `6a47fef4` 在侧栏展开后出现中英双份 `[Gmail]/...` 系统目录（如 `已加星标 · [Gmail]/已加星标` 与 `已加星标 · [Gmail]/Starred`、`重要邮件 · [Gmail]/重要` 与 `重要邮件 · [Gmail]/Important`、`所有邮件 · [Gmail]/所有邮件` 与 `所有邮件 · [Gmail]/All Mail` 等 7 组 14 行）；同时 `[Gmail]/重要`（库内有 369 条 `MessageLocation`）与 `[Gmail]/Important`（0 条）在 `folder-stats` 中均错误返回与 `所有邮件` 一致的 `total_count=228`。
- 影响：
    1. 任何在服务端发生显示语言切换或系统目录重命名/删除的账号（已确认实发于 Gmail `6a47fef4`，同类缺陷也覆盖所有 IMAP/Graph 目录删改后残留旧行的场景），旧目录会作为已消失僵尸目录与新目录长期并存并被侧栏以消歧命名展示，甚至旧目录仍保有历史消息定位（如 `[Gmail]/已发邮件` 保留 2 封），新旧视图计数与归属分裂；
    2. 全量 Gmail 账号的 `\Important` 视图均存在 `role='other'` 断裂，导致 `view_scope_folder_ids` 把 Important 视图错投影为 All Mail 全量集合，并在双视图并存时导致 `_label_view_folders` / `_important_view_id` 只命中单侧行。
- 根因（开发铁律视角：本质是 `Folder` 正交维度坍缩与协议角色链路未收口，外部 Gmail `IMAP LIST` 返回语言切换触发暴露，已实测 `6a47fef4` 在 `2026-10-26` 返回中文 modified UTF-7 且当前与 `2026-11-25 04:27:28Z` 均返回英文 `[Gmail]/...`，同邮箱 `uidvalidity` `2/3/4/5/6` 一一相同）：
    1. **身份与本地化路径未分离**（`src/mail_core/mail/storage/models.py:133-150`、`src/mail_core/sync/engine.py:289-351`）：`Folder` 以 `(account_id, remote_id)` 为实体键，而 IMAP/Gmail 将显示语言编码进 `remote_id`。服务商换名时 `sync_account_folders` 直接新建第二套 `Folder` 行，未基于系统唯一角色/`UIDVALIDITY` 执行同实体重绑定与原子合并，导致位置与检查点分裂。
    2. **三类正交状态坍缩在 `folders.sync_status` 与前后端特判**（`src/mail_core/mail/domain/enums.py:24-37`、`src/mail_core/sync/engine.py:294-309`）：与 `t076` 改造前的 `Account.sync_status` 同构，`folders.sync_status = 'paused'` 混装了「服务端仍存在但 `\Noselect` 的结构节点（如 `[Gmail]`/`Other`）」与「远端已消失/改名目录」，且枚举残存未用的 `running`/`failed`/`auth_failed`；`engine.py:296` 还限定 `existing.kind == CONTAINER`，完全漏掉 `VIEW`（使 `[Gmail]/所有邮件` 与 `[Gmail]/重要` 永久保持 `idle`）。
    3. **协议角色契约断裂与前端猜角色补丁**（`src/mail_core/mail/domain/enums.py:13-22`、`src/mail_core/providers/imap.py:1044-1074`、`src/mail_core/mail/application/queries.py:203-215`、`src/mail_core/sync/metadata.py:219-232`、`src/frontend/src/components/Sidebar.tsx:56-103`）：`FolderRole` 缺失 `flagged` 与 `important`；Gmail `IMAP LIST` 明确携带 RFC 6154 `\Important`，但 `imap.py` 漏判 `\important` 且查 `_FOLDER_ROLE` 未剥离 `[Gmail]/` 前缀，导致所有 Gmail 的 Important 视图均为 `role='other'`；`view_scope_folder_ids` 只判定 `folder.role == "important"`，直接误落入 All Mail 全量容器；`_label_view_folders` 单键值覆盖写错目标 ID；前端 `Sidebar.tsx` 只得靠 `inferEffectiveRole` 字符串启发式兜底，并因 `folderDisplayNames` 无区别展示已消失旧行而渲染双份目录。
    4. **同类下游位点**：`queries.py:245-273`（`list_folder_stats_for_account`）未排除远端消失目录；`queries.py:379`（`unified_inbox(folder_role=...)`）与 `queries.py:536`（`_query_inbox_stats`）未按活跃存活目录过滤，同角色多行可毒化统计为 `null`；`mutations.py:54-63`（`_primary_location`）与 `mutations.py:365-385`（`mark_all_messages_read`）选远端写回目标时未限定活跃 `container`，可能选中已消失旧 `remote_id`；`label_backfill.py:61-68` `_important_view_id` 仅取单个 `scalar()` 行；`remote_image_proxy.py` 等非目录模块无此类问题。
- 彻底重构方向（零兼容负担）：废除过载的 `folders.sync_status` 拆分为正交属性（`kind`、`selectable: bool`、`remote_state: 'active' | 'missing'`）并同步更新 OpenAPI 与前端；补齐 `FolderRole` 与 `imap.py` `\important`/`[Gmail]/` 权威识别及单一视图判定；重构 `sync_account_folders` 为全类型（含 `VIEW`）同实体重绑定原子合并 + 消失统一置 `missing`；一次幂等 Alembic 迁移洗净存量 `Important` 的 `role='other'` 与已并存的中英双份系统目录；收口 `queries`/`mutations`/`label_backfill`/`Sidebar.tsx` 仅服务活跃与可选目录并消除前端字符串兜底。
- 测试缺口：
    1. `test_gmail_sync_strategy_and_timeout.py` / `test_imap_gm_labels.py` 夹具缺少 `\Important` SPECIAL-USE 标志，未覆盖 `ImapProvider -> sync_account_folders -> view_scope_folder_ids` 全链路；
    2. `test_gmail_label_views.py` 直接 seed `Folder(role="important", kind=VIEW)`，掩盖了真实 IMAP 导入为 `role="other"` 导致 `view_scope_folder_ids` 误算为 All Mail 的缺陷；
    3. `test_gmail_label_views_discovery.py` 只测单次发现，未测中英前后两次发现切换（含 `CONTAINER` 与 `VIEW` 的重绑定合并、`MessageLocation`/`SyncCheckpoint` 保留与旧行消除）；
    4. `test_sync_retry_queue.py`、`test_a320_folder_pause_revival.py`、`queries`、`mutations` 与 `Sidebar.test.tsx` 均需随正交状态模型更新断言并验证远端已消失目录不再污染展示、角色统计与远端写回。
- 线索：`.scratch/repro_p100.py`（实测复现 `\Important -> role='other'`、`view_scope_folder_ids` 跌入全量容器、以及中英切换后产生 7 个双份旧/新混合目录）。
- 处理：t092；resolution=transferred；reason=已按开发铁律核实目录正交状态模型、IMAP角色收口、系统目录同实体重绑定合并与历史清洗范围并转交 t092
