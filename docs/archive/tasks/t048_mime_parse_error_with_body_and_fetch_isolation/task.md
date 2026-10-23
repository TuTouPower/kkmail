---
tid: "t048"
slug: "mime_parse_error_with_body_and_fetch_isolation"
title: "保留解析报错邮件可读正文并解耦远端拉取错误与复用 IMAP 连接"
status: "done"
branch: "t048_mime_parse_error_with_body_and_fetch_isolation"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "0c8c13278374c46de79d3732554b6eb74406ca3e"
depends_on: ""
conflicts_with: ""
note: "来源 p031；用户确认严格提示解析错误但同时展示可读正文，剥离 fetch_mime 拉取错误并复用同批 IMAP 连接。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 根因修复与架构调整：
   - 严格报错与可读正文保留（AC-001）：改造 `parse_mime_content`，遇到编码/报头缺陷时捕获 `first_error`，同时通过多编码安全回退完整提取可读正文与附件挂载于 `MimeParseError`；`run_archive_batch` 捕获后记录 `body.parse_error` 但保留提取出的 `text_plain` / `text_html`，不予清空。
   - 阅读器与列表告警展示（AC-002）：改造 `MessageReader`，当 `detail.parse_error` 非空且存在正文时，同时渲染 `MR-PARSE-ERROR` 告警框与正文；若正文为空则仅渲染告警框无空占位；`_body_previews` 移除对 `parse_error.is_(None)` 的过滤。
   - 远端拉取错误严格解耦（AC-003）：`run_archive_batch` 捕获 `fetch_mime` 异常时仅写入 `MessageArchiveState.last_error`，移除对 `MessageBody.parse_error` 的写入；未归档邮件按需同步与重试入口保持畅通。
   - 同批归档 IMAP 连接复用（AC-004）：在 `ImapProvider` 增加 `open_session` 与 `close_session`，`fetch_mime` 优先复用当前连接并按需切换 `SELECT`，批次结束统一登出，避免重复高频 `LOGIN`/`LOGOUT`。
2. 规范与文档同步：更新 `docs/blueprint/conventions.md` §九「MIME 解析与错误可见性规范」，固化拉取与解析解耦、报错与可读正文并存契约。

## Review 处置

### Round 1 (2026-10-23T23:25:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 39 文件 266 项全通；`(cd src/desktop && npm test)` 全通；`pytest .repo_template/tests -q -m contract` 150 项全通；`scripts/run-mail-core-tests.sh run` PostgreSQL 相关用例全通。
- 黑盒：`npm --prefix src/frontend run test:e2e`（14 项全部通过）；`python3 scripts/run_full_stack_e2e.py`（8 项全栈真实端到端测试全通）。
- review：`review_code.md` PASS（0 finding），`review_test.md` PASS（0 finding），指纹一致。
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复局部编码瑕疵 MIME 邮件丢弃正文缺陷，实现解析错误严格报错与可读正文并存渲染，剥离 fetch_mime 远端网络错误不写入 parse_error，同批次多封 IMAP 邮件归档复用单次连接会话。遗留：无。
