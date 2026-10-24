# p037 邮箱文件夹角色重复显示与名称映射错误

- 现象：侧栏逐个显示远端文件夹，但按 `role` 把特殊文件夹统一改名。25 个 Graph 账号各有两条 `role=inbox`（`INBOX` + `Inbox` 或 `收件箱`），因此同一账号会出现两个“收件箱”。16 个账号同时有 `role=sent` 的“已发送邮件”和 `role=other` 的“发件箱”；另 9 个账号有 `role=sent` 的 `Sent Items`，以及 `role=other` 的 `Outbox`、`Conversation History`。3 个 QQ IMAP 账号的 `Deleted Messages` 被存为 `other`。
- 影响：侧栏名称无法区分不同远端收件箱，用户容易误选。数据库检查未发现重复 inbox 文件夹间有同一邮件位置，因此不能按 `role` 直接删除或合并；这些记录可能是远端别名或独立目录，需保留选择能力。16 个 Graph 账号的“发件箱”与“已发送邮件”并存，9 个账号有 `Outbox`、`Conversation History`；这些是不同远端目录，当前没有证据证明它们等同于“已发送”，不应按名字强制映射或合并。QQ“其他文件夹/QQ邮件订阅”父子路径符合远端目录层级，不作为本条缺陷。
- 根因：`Sidebar.tsx` 对每个 `role=inbox` 目录使用同一标准标签并逐条渲染，未处理同角色目录名称冲突。IMAP `_FOLDER_ROLE` 未包含 `Deleted Messages`，导致 QQ 删除目录落为 `other`。共享 `sync_account_folders` 按 `remote_id` upsert、不清理远端已消失目录；它可能导致陈旧记录，但本次 Graph 重复的来源尚未确认。
- 测试缺口：`Sidebar.test.tsx` 只给每账号一个 inbox，未覆盖同角色重复标签；IMAP 映射测试未覆盖 `Deleted Messages`。应补同角色目录侧栏呈现和 IMAP 删除目录映射，并断言不同 `folder_id` 仍可单独访问、不会按角色误删或合并；同时断言 `Outbox` / `Conversation History` 不会误归入 `sent`。
- 线索：`.scratch/mailbox_folder_grouping_repro.sql`；当前 25 个 Graph 账号均有重复 inbox role，三个 QQ 账号均有 `Deleted Messages` role=`other`。
- 处理：t051
