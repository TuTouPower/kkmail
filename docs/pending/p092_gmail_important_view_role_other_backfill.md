---
pid: "p092"
slug: "gmail_important_view_role_other_backfill"
status: "closed"
resolution: "resolved"
reason: "_important_view_id 改为按 kind=view 且 role=important 或精确 remote_id 识别，新增 role=other 生产形态 PG 用例；定向 PG 22 passed、unit 1694 passed"
fix_ref: "main"
---
# p092 回填把 role=other 的 Gmail Important 视图误判为不存在

- 现象：生产执行 `python -m mail_core --backfill-gmail-labels` 后，5 个 Gmail 账号全部返回 `skipped_no_view`，历史 Important 成员未回填。
- 影响：t088 的一次性回填在生产不可用；t086 的 Important 视图仍缺历史成员。All Mail 视图不受影响。
- 根因：生产库中 Gmail Important 目录的 `remote_id` 为 `[Gmail]/Important` 或 `[Gmail]/&kc2JgQ-`、`kind='view'`，但 `role='other'`（t056 只补了 `\All`/`\Flagged` 的 RFC6154 映射，`\Important` 未映射）。`mail_core.sync.label_backfill._important_view_id` 仅按 `Folder.role == "important"` 查找，漏掉了实际视图；PG 测试 fixture 把该目录造为 `role='important'`，因此未发现。
- 测试缺口：新增 PG 用例，Important 视图 fixture 使用生产真实形态（`role='other'` + 精确 remote_id + `kind='view'`），断言回填成功并写入成员。
- 线索：生产 SQL 查询显示 5 个 Gmail 账号均有 `kind='view'` 目录但 `role` 集合只有 `all, drafts, flagged, inbox, junk, other, sent, trash`；回填命令输出 `skipped_no_view`。
- 处理：main；resolution=resolved；reason=\_important_view_id 改为按 kind=view 且 role=important 或精确 remote_id 识别，新增 role=other 生产形态 PG 用例；定向 PG 22 passed、unit 1694 passed
