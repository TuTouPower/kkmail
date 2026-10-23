# p031 已修正阅读副本写入 parse_error 致正文被互斥屏蔽及远端拉取失败混用 parse_error

- 现象：
    1. 打开腾讯企业微信邮件「微信收到的好友申请，可在企业微信通过」（`[REDACTED_EMAIL]`）时，阅读器正文区仅显示红字「邮件解析失败：原始 MIME 的 viewport 属性含错误 quoted-printable 编码；已显式修正阅读副本，原始邮件完整保留。」，明明提示“已显式修正阅读副本”，却完全不渲染已修正的 12,827 字节 HTML 正文。
- 影响：
    1. 库内 5 封已完成阅读副本修复且 `text_html` 完整有效（`6095`–`12827` 字符）的邮件（4 封企业微信 `[REDACTED_EMAIL]`、1 封微信团队 `[REDACTED_EMAIL]`「找回微信密码」）因 `message_bodies.parse_error` 被写入修复说明，在阅读器中全部被当成致命解析失败而屏蔽正文，且列表页 `body_preview` 摘要回退一并失效。
    2. 生产归档解析器 `parse_mime_content` 对腾讯企业微信等真实邮件中 `<meta name="viewport" content="width=device-width">` 未转义 `=de`（quoted-printable 解出单字节 `0xDE`）或 HTML 闭合标签后尾部多余非法字节直接抛出 `MimeParseError` 并清空整封邮件正文（`text_html=None, text_plain=None`）。
    3. 同类 `parse_error` 混用位点：`run_archive_batch` 在 `provider.fetch_mime` 发生网络/限流错误（如网易 IMAP `error: [ALERT] Too many login attempts, try again later`，当前库内共 383 封邮件）时，将拉取错误写入 `MessageBody.parse_error`，导致阅读器误报「邮件解析失败」且阻断按需同步与手动重试按钮。
- 根因：
    1. 数据修复脚本与阅读器互斥契约冲突（数据/产品耦合）：
        - `[REDACTED]:86-102` 与 `[REDACTED]` 在修复 `[REDACTED_UUID]`、`[REDACTED_UUID]`、`[REDACTED_UUID]`、`[REDACTED_UUID]`、`[REDACTED_UUID]` 共 5 封邮件的 `message_bodies.text_html` 时，将审计说明写入了 `message_bodies.parse_error`；
        - 但 `src/frontend/src/components/MessageReader.tsx:194-213`（及 `docs/blueprint/conventions.md` §九.3）将 `detail?.parse_error` 作为最高优先级互斥错误分支：只要 `parse_error` 非空，即只渲染 `MR-PARSE-ERROR` 告警框并跳过 `detail.body` 渲染；同时 `src/mail_core/mail/application/queries.py:121`（`_hydrate_body_previews`）过滤 `MessageBody.parse_error.is_(None)`，导致这 5 封邮件的正文与列表预览全部被屏蔽。
    2. 生产 MIME 正文解析器对局部编码瑕疵零容忍（产品缺陷，`src/mail_core/blobs/archive.py:167-187, 776-789`）：
        - 腾讯企业微信发送的 `Content-Type: text/html; charset="gb2312"` + `Content-Transfer-Encoding: quoted-printable` 邮件在 `<meta name="viewport" content="width=device-width">` 中未将 `=` 编码为 `=3D`，Python QP 解码将 `=de` 解为字节 `0xDE`，触发 `gb2312` `strict` 解码 `UnicodeDecodeError`；
        - `parse_mime_content` 在 `archive.py:168, 185` 直接抛出 `MimeParseError("body", ...)`，`run_archive_batch`（`archive.py:781-789`）随即丢弃全部正文写入 `text_html=None, text_plain=None, parse_error=...`。
    3. 已确认同类位点清单：
        - `src/mail_core/blobs/archive.py:613-646` + `src/mail_core/api/mail.py:317-323` + `src/frontend/src/components/MessageReader.tsx:59-61, 194-213`：`provider.fetch_mime(remote_id)` 远端拉取失败（网络超时、IMAP 登录频控 `Too many login attempts` 等，非 MIME 解析失败）时，`archive.py:638-643` 将拉取异常写入 `MessageBody.parse_error`（即使状态仍为 `ARCHIVE_PENDING` 待重试）。由于 `parse_error` 非空：`api_get_message`（`mail.py:322` `and not d.parse_error`）拒绝提权入队按需归档，`MessageReader.tsx:59-61`（`isPendingArchive` 要求 `!detail.parse_error`）不触发自动同步且不渲染「立即拉取正文 / 立即重试同步」按钮，反而直接展示「邮件解析失败：error: [ALERT] Too many login attempts, try again later」（当前库内 383 封邮件受影响）。
        - `src/mail_core/providers/imap.py:500-537` + `src/mail_core/blobs/archive.py:614`：`run_archive_batch` 每批 20 封邮件逐封调用 `provider.fetch_mime(remote_id)`，每次调用均新建 TCP/SSL 连接并执行 IMAP `LOGIN` + `SELECT` + `LOGOUT`，短时间高频登录直接触发网易 163/126 `[ALERT] Too many login attempts, try again later`。
- 测试缺口：
    1. `tests/mail_core/test_on_demand_body_sync.py:187-207`（`test_ac005_sync_body_captures_provider_or_parse_error`）：测试假定远端拉取超时也应写入 `MessageBody.parse_error`，混淆了“远端拉取失败（可重试，`MessageArchiveState.last_error`）”与“MIME 语义解析失败（`MessageBody.parse_error`）”，导致拉取失败邮件在阅读器中被永久锁死在 `MR-PARSE-ERROR` 无重试入口。
    2. `tests/mail_core/test_archive_decode_failure.py`：仅测试了完全损坏字节流抛 `MimeParseError`，未覆盖企业微信等真实邮件的未转义 QP `=de` 或尾部填充字节场景，也未验证已修复正文记录不应保留非空 `parse_error` 阻断渲染。
- 线索：
    - `.scratch/repro_repaired_mime_parse_error_and_fetch_error.py`
    - `[REDACTED]:86-102`
    - `src/frontend/src/components/MessageReader.tsx:59-61, 194-213`
    - `src/mail_core/mail/application/queries.py:121`
    - `src/mail_core/blobs/archive.py:167-187, 613-646, 776-789`
    - `src/mail_core/api/mail.py:317-323`
- 处理：未开
