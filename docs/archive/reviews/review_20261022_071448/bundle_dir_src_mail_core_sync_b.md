# Bundle Review — dir:src/mail_core/sync_b

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 1 allowlisted tracked files

## Findings

- [Medium][95] src/mail_core/sync/remote_push.py:31-L42 — RateLimitedError 可能被判永久失败且忽略 Retry-After — 证据：错误分类只查看 status_code 或 response，不识别异常的 .status=429；重试延迟又不读取 .retry_after_seconds，某些 429 进入 FAILED。 — 依据：src/mail_core/providers/http.py:26-44 暴露 typed status 与 retry_after。 — 修复：按 ProviderHttpError/RateLimitedError 类型分类并遵守 Retry-After。

## Files examined

- src/mail_core/sync/remote_push.py
