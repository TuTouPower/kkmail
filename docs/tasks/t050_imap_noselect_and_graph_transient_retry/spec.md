# Task spec

## 背景

1. QQ IMAP 返回的“其他文件夹”等分类容器带有 `\Noselect` / `\NonExistent` 属性，RFC 3501 规定客户端禁止对其执行 SELECT 或操作邮件。目前 `ImapProvider.list_folders()` 未过滤 `\Noselect` 标志，导致容器目录作为普通邮件文件夹入库并在同步时对其执行 `UID SEARCH` 触发服务端拒绝（`NO`），导致任务失败。
2. Outlook Graph 账号在同步过程中遇到公网/微软服务端瞬态网络抖动（TLS 连接提前断开，如 SSLEOFError、RemoteDisconnected）以及 HTTP 503（Service Unavailable），未在传输层进行有限退避重试，直接抛出 `ProviderHttpError` 导致同步任务被标记失败并中断。

## 契约区

### 范围

- 在 `src/mail_core/providers/imap.py` 的 `list_folders` 中解析 IMAP mailbox 属性，过滤带有 `\noselect` 或 `\nonexistent` 属性的文件夹，不作为可同步文件夹返回。
- 在 `src/mail_core/providers/imap.py` 的 `fetch_metadata_page` 等入口中，对历史已入库或服务器拒绝的不可选文件夹（SELECT / UID SEARCH 返回 NO）进行安全处理，避免抛出异常污染全局同步状态。
- 在 `src/mail_core/providers/oauth.py` 的 `urllib_json_request` 传输层中，针对 HTTP 503（Service Unavailable）和传输层 TLS/连接断开异常（如 SSLEOFError、RemoteDisconnected、ConnectionResetError 等）提供有限次数的指数退避重试（最多 3 次，尊重 `Retry-After` 头）。
- 为 `\Noselect` 文件夹过滤和 Graph 传输层 503/TLS 瞬态重试编写自动化单元测试。

### 非范围

- 重新获取用户已失效的凭据（如 QQ 邮箱密码/授权码失效、wangyun77666 OAuth 401 授权过期）。
- 更改数据库表结构或数据库迁移。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：`ImapProvider.list_folders()` 过滤包含 `\noselect` 或 `\nonexistent` 属性的 mailbox，只返回可用于存放邮件的有效文件夹。
- [ ] AC-002：`ImapProvider.fetch_metadata_page()` 在遇到不可选文件夹时（SELECT 或 UID SEARCH 返回 NO 且属于不可选目录）安全返回空页并标记结束，不抛出 RuntimeError 崩溃。
- [ ] AC-003：Graph API 传输层在遇到 HTTP 503 Service Unavailable 时，自动按照 `Retry-After`（或指数退避）重试，在重试成功后正常返回结果。
- [ ] AC-004：Graph API 传输层在遇到网络瞬断（TLS SSLEOFError、RemoteDisconnected、ConnectionReset 等）时，自动进行有限次数的重试并在恢复后成功返回。
- [ ] AC-005：HTTP 503 或网络瞬断在重试次数超过上限（3 次）后，传输层才向上层抛出清晰脱敏的 `ProviderHttpError`。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：用户汇报与生产错误日志（QQ IMAP 对“其他文件夹”UID SEARCH 返回 NO；Outlook Graph 遇到 TLS 提前断开与 HTTP 503）

### 有意不测

- 无

### 测试策略

- 单元测试：模拟返回包含 `\Noselect` 标志的 mailbox LIST 响应，断言 `list_folders()` 过滤结果；模拟不可选文件夹 `fetch_metadata_page()` 行为。
- 传输层测试：使用 mock 模拟 503 响应（含/不含 Retry-After）及 TLS EOF / RemoteDisconnected 异常，断言重试次数、退避间隔及成功/耗尽行为。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：重试延迟设置过长可能阻塞 worker；限制单次最大重试次数为 3 次，单次退避上限为 10 秒。
- 回退：git revert 本 task commit。

### 依赖与约束

- 无

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：记录 IMAP 文件夹过滤规则与 Graph 传输层瞬态重试机制。
