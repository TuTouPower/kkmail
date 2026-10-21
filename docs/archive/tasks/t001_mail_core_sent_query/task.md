---
tid: "t001"
slug: "mail_core_sent_query"
title: "支持按角色查询已发邮件与映射IMAP已发目录"
status: "done"
branch: "t001_mail_core_sent_query"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "d7e829a4a81c9f9c0f9153d6bc57d86d0a188ad7"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. `imap.py`：`_FOLDER_ROLE` 映射新增 `"已发送"` 与 `"已发送邮件"`，并在 `list_folders` 中支持匹配 `\Sent` 标志解析出 `role="sent"`。
2. `queries.py` 与 `api/mail.py`：`unified_inbox` 与 `/api/mail/inbox` 增加 `folder_role: str = "inbox"` 参数，支持查询指定角色文件夹（如 sent），并兼容默认 inbox。
3. 测试驱动：新增 `tests/mail_core/test_folder_role_inbox_api.py`，扩展 `tests/mail_core/test_imap_remote_id.py`，全量测试与构建验证通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-22T04:55:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`pytest .repo_template/tests -q -m contract`、`(cd src/frontend && npm test && npx tsc -b && npm run build)`、`(cd src/desktop && npm test)`、`pytest tests/mail_core/test_folder_role_inbox_api.py tests/mail_core/test_imap_remote_id.py` 全绿通过。
- 黑盒：`npm --prefix src/frontend run test:e2e` 冒烟通过（2 passed）。
- review：`review_general.md` verdict: PASS (Round 1)。
- AC 证据：见 `handoff.json`

### 结果摘要

- 成功支持 `/api/mail/inbox?folder_role=sent` 跨账号/单账号已发送邮件查询与 keyset 分页，并补齐 IMAP 中文目录与 `\Sent` 标志映射。
