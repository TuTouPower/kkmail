# Task review t012（reviewer_focus: 代码）

- task：`t012_mark_read_convergence`
- spec：`docs/tasks/t012_mark_read_convergence/spec.md`
- diff_anchor：`330008b1dfc166f67b60766d639b697d04e37915`
- target：`git -C '/Users/karson/kar/code/kkmail_t012' diff 330008b1dfc166f67b60766d639b697d04e37915`
- round：1
- reviewed_at：2026-10-23T01:50:00+08:00

reviewed_scope: f30230e1109360c5

## Findings

无。

## 结论

- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：代码严格修复 p016 确认的三项核心根因。运行中 claimed 任务通过载荷记录后续唤醒，在任务完成（complete_job）后原子调度新 pending 任务，彻底解决超过 20 条批次余量丢失调度问题；入站同步（metadata upsert 与 delta flag patch）严格以 `get_unconverged_field_intents` 保护本地待处理和完成窗口内的意图不被旧快照覆盖；`recompute_folder_stats` 在已有统计行场景下强制在 SQL 聚合前 flush 会话，消除 ORM 状态滞后导致的角标失真；提供幂等的 `reconcile_account_writeback_and_stats` 账号恢复入口。
- 系统性 follow-up：无

verdict: PASS
