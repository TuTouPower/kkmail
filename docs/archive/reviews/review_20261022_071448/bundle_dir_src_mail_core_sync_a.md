# Bundle Review — dir:src/mail_core/sync_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][95] src/mail_core/sync/delta.py:316-L338 — provider 异常原文会被持久化到任务与账号状态 — 证据：str(exc) 被写入 WorkerJob payload/detail、Account.config.last_sync_error 和 remote operation；异常可能包含响应 body 或敏感文本，路径未统一使用 safe_error。 — 依据：docs/guides/security.md:63 禁止持久化 provider 响应体。 — 修复：所有持久化只保存异常类型/HTTP 状态摘要，移除原始响应文本。
- [Medium][100] src/mail_core/sync/engine.py:79-L101 — 限流时既排 Retry-After 任务又让当前 job 按短退避重试 — 证据：限流分支已 enqueue 延后任务并返回 rate_limited；worker handler 随后把当前 job 当普通失败再次短退避重排，导致 Retry-After 前重复请求并多出队列任务。 — 依据：src/mail_core/sync/delta.py:302-315；src/mail_core/worker/handlers.py:19-28,67-92,138-153。 — 修复：原 job 完成并只保留带 Retry-After 的重试，或直接更新原 job 的 run_after。
- [Medium][99] src/mail_core/sync/engine.py:62-L76 — provider 构造失败发生在 lease/claim 清理保护区之外 — 证据：获取并提交 lease 后才 build_provider()，但 try 从后续网络路径开始；坏凭据/构造异常会留下 lease，重试需等过期。archive 也先 claim 再构造 provider。 — 依据：相关路径见 sync/delta.py:227-255、sync/remote_push.py:89-133、blobs/archive.py:394-446。 — 修复：在 claim 前构造 provider，或在 claim 后立即进入覆盖构造的 try/finally 并释放 lease/reset claim。

## Files examined

- src/mail_core/sync/__init__.py
- src/mail_core/sync/checkpoints.py
- src/mail_core/sync/delta.py
- src/mail_core/sync/engine.py
- src/mail_core/sync/jobs.py
- src/mail_core/sync/leases.py
- src/mail_core/sync/metadata.py
- src/mail_core/sync/reconcile.py
