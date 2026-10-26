# Task review t056（reviewer_focus: 代码）

## Round 1 (2026-10-26T23:30:00+08:00)

- reviewed_at: 2026-10-26T23:30:00+08:00
- reviewed_scope: e7c80477ce7bcb4d
- reviewed_commit: `6105e02`

最终代码复审 PASS。
AC-001 ~ AC-005 均严格按 spec 实现：
1. `src/mail_core/sync/engine.py`: 在 `sync_account_folders` 中识别 Gmail 并将 `\All` 与 `\Important` 虚拟文件夹默认设为 `paused`，仅非 paused 文件夹入队 `SYNC_FOLDER_METADATA`；`max_pages` 默认参数改为 10。
2. `src/mail_core/providers/imap.py`: 补齐 RFC 6154 的 `\all` 与 `\flagged` 映射，默认 timeout 放宽至 60.0s。
3. `src/mail_core/providers/factory.py`: 回退默认超时放宽至 60.0s。
4. `src/mail_core/worker/handlers.py`: 瞬态网络超时在重试期间不修改账户状态为 failed。
实现精准，未引入无关范围改动。零 finding。

verdict: PASS
