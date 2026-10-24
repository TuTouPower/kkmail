# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-10-25T05:22:51+08:00 agent → developer

- 当前焦点：逐项实施 `docs/reviews/review_20261025_020805/adoption_decision.md` 中已批准项；每项在独立分支/worktree 中实现、验证、提交并快进合入 `main`，不 push。
- branch：main
- head_commit：aa126fb827a3ab525640fe7779a32a9b5f3aaa1c
- 已完成：A1–A60 均可从 main 提交的 `Adoption-ID` trailer 追溯；A6 本次更新交接记录并归档旧段落。
- 未完成：A61–A296；按 adoption 决策顺序继续，已合入项不重复执行。
- 陷阱：测试数据库只能经 `scripts/run-mail-core-tests.sh` 及其 owned database guard 操作；不要直连业务数据库。
- 下一步：继续 A61，保持每项独立 commit 与 main 快进合并。
