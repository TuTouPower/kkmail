# Bundle Review — dir:src/frontend/src/components_b

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 4 allowlisted tracked files

## Findings

- [Low][94] src/frontend/src/components/Sidebar.tsx:16-L90 — 侧栏统计请求失败会显示为零未读 — 证据：单账号 folder-stats 异常被 catch 并转为 0；全局 stats 与兜底失败后仍用零显示，用户无法区分真实零值与加载失败。 — 依据：docs/specs/inbox_ui_and_search.md AC-001 要求精准计数。 — 修复：失败时显示未知或不可用状态，不伪装成零。
- [Low][99] src/frontend/src/components/SettingsModal.tsx:213-L218 — 创建分组失败会清空输入，同一 helper 会覆盖同步任务结果消息 — 证据：run() 捕获错误并正常返回，调用方 await 后无条件清空 groupName；sync-all 回调的数量消息也被通用成功文案覆盖。 — 依据：失败时应保留用户输入并准确呈现操作结果。 — 修复：让 run 返回成功状态，仅成功时清空；保留具体回调消息。

## Files examined

- src/frontend/src/components/SettingsModal.test.tsx
- src/frontend/src/components/SettingsModal.tsx
- src/frontend/src/components/Sidebar.test.tsx
- src/frontend/src/components/Sidebar.tsx
