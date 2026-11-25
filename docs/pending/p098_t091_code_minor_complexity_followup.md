---
pid: "p098"
slug: "t091_code_minor_complexity_followup"
status: "todo"
---
# p098 t091 代码次要收口：拆分 apply_remote_operations、open_idle_session 与 push_remote_operations 高复杂度分支

- 来源：t091 遗留（Round 2 `review_code.md` 1 条非阻断 `minor`：`t091_code_f005`）
- 内容：拆分 `src/mail_core/providers/imap.py` 中 `ImapProvider.apply_remote_operations`（CC 90 / 全文件 1966 行）与 `open_idle_session`（CC 17）及 `src/mail_core/sync/remote_push.py` 中 `push_remote_operations`（CC 88 / 全文件 843 行）的异常分流与单条结算分支至独立私有辅助函数，降低圈复杂度与文件行数。因不涉及可观测行为缺陷且已通过 Round 2 全部 `PASS` 门禁，留待专项清理收口。
- 处理：未开
