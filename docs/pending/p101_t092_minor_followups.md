---
pid: "p101"
slug: "t092_minor_followups"
status: "closed"
resolution: "resolved"
reason: "已移除 engine.py:29 与 patrol.py:29 未用 CONTAINER/is_view_folder 导入并同步 account_connection.md 派生视图表述；相关 PG 26 passed、契约 389 passed, 1 skipped、前端 56 文件 599 passed、桌面端 12 项与敏感扫描通过"
fix_ref: "main"
---
# p101 t092 次要收口：清理 sync/engine 与 patrol 死导入并同步 account_connection 过时表述

- 来源：t092 遗留（Round 3 `review_code.md` 1 条非阻断 `minor`：`t092_code_f012`，及范围外文档观察）
- 内容：清理 `src/mail_core/sync/engine.py:29` 的未用 `CONTAINER` 导入与 `src/mail_core/sync/patrol.py:29` 的未用 `CONTAINER`/`is_view_folder` 导入，并同步更新 `docs/specs/account_connection.md:31` 仍提及已废止的 Gmail 虚拟标签默认 `paused` 旧描述；因零行为影响且为保持 `t092` 已审 `review_scope` 不可变性，留待独立微清理。
- 处理：main；resolution=resolved；reason=已移除 engine.py:29 与 patrol.py:29 未用 CONTAINER/is_view_folder 导入并同步 account_connection.md 派生视图表述；相关 PG 26 passed、契约 389 passed, 1 skipped、前端 56 文件 599 passed、桌面端 12 项与敏感扫描通过
