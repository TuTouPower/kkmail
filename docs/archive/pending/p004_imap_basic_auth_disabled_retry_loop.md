# p004 Outlook 停用普通密码登录导致 Worker 盲目重试且未明确置停

- 现象：配置或导入以普通密码（IMAP）连接的 Outlook/Hotmail 账号时，后台 Worker 持续报错抛出 `imaplib.IMAP4.error: Basic authentication is disabled`，任务反复重试并堆积在任务队列中，未能自动将账号置为停用或向用户呈现明确的永久性认证失败状态。
- 影响：系统 CPU 与网络连接无意义消耗，队列被无效连接占用，前端用户仅看到账号处于同步中或不断失败，无法理解具体是密码错误还是服务商策略变更。
- 根因：微软已在公网彻底关闭消费级邮箱的 IMAP Basic Auth，`ImapProvider._connect` 遇到服务商明确返回的 `Basic authentication is disabled` 异常时，被当作普通的瞬时网络/认证异常捕获，未将其归类为不可恢复的凭据失效（`PermanentAuthError`），且未在应用层自动将 `Account.sync_enabled` 置为 False 并记录明确的人类可读原因。
- 同类位点：Gmail 遇到关闭低安全性应用、163/QQ 邮箱使用普通密码而非授权码时的同类错误捕获。
- 测试缺口：现有 IMAP 单元测试使用本地 Dovecot 夹具（支持并允许普通密码），未模拟真实公网邮件服务商明确禁用 Basic Auth 的拒绝响应。应在 Provider 单元测试与 Handler 集成测试补充该异常的分类处理断言。
- 线索：部署新容器后 Worker 日志反复打印 `imaplib.IMAP4.error: Basic authentication is disabled.` 导致推入的出站操作被阻断。
- 处理：fix/p001-p004
