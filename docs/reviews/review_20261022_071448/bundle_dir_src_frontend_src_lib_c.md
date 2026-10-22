# Bundle Review — dir:src/frontend/src/lib_c

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][100] src/frontend/src/lib/mailBody.ts:47-L48 — 邮件 iframe 允许弹窗逃离 sandbox，与安全契约冲突 — 证据：sandbox flags 含 allow-popups-to-escape-sandbox，新窗口不再继承 iframe sandbox 限制；测试也固化了该标记。 — 依据：docs/specs/inbox_ui_and_search.md:42 与 docs/guides/security.md:42 明确要求只保留 allow-popups；上一轮采用记录 A17 又要求保留，权威状态冲突。 — 修复：按决策治理确定契约，并同步实现、spec、安全指南及测试。
- [Low][98] src/frontend/src/lib/mailBody.ts:50-L55 — 旧生产 helper 仅被单测调用且注释仍描述已取消的回复功能 — 证据：htmlToText 仅测试引用，注释描述回复/转发引用；canSendFrom 与旧 EventSource helper 也无生产调用，测试仍覆盖旧路径。 — 依据：产品范围明确不含发信；当前实时 hook 使用 subscribeMailCoreStream。 — 修复：移除确认废弃的 helper 或让测试覆盖实际生产调用路径。

## Files examined

- src/frontend/src/lib/mailBody.test.ts
- src/frontend/src/lib/mailBody.ts
- src/frontend/src/lib/mailDate.test.ts
- src/frontend/src/lib/mailDate.ts
- src/frontend/src/lib/mailKey.test.ts
- src/frontend/src/lib/mailKey.ts
- src/frontend/src/lib/previewText.test.ts
- src/frontend/src/lib/previewText.ts
