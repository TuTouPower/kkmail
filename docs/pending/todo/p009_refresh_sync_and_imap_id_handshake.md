# p009 邮件列表刷新未触发后端同步且网易IMAP缺少ID握手拦截

- 现象：前端收件箱列表头部“刷新”按钮仅使本地查询缓存失效，不触发后端远端拉信，新账号或空收件箱刷新后无任何邮件；新创建/导入账号未自动入队首次同步任务；网易 163 等 IMAP 邮箱因未发送 RFC 2971 ID 握手被服务端拦截报错 `SELECT Unsafe Login`。
- 影响：用户在主收件箱界面无法主动触发远端同步；新添加邮箱在后台不会自动拉取文件夹与邮件；网易 163/126 邮箱无法正常进入收件箱收取邮件。
- 根因：
    1. `src/frontend/src/components/MessageList.tsx` 的 `refreshView()` 仅执行 `queryClient.invalidateQueries({ queryKey: ['mail-core'] })`，未调用 `POST /api/accounts/{id}/sync` 或 `sync-all`；
    2. `src/mail_core/mail/application/accounts.py` 的 `create_account_app` 仅写入账号与凭据，未调用 `enqueue_account_sync` 入队初始 `SYNC_ACCOUNT_FOLDERS` 任务；
    3. `src/mail_core/providers/imap.py` 在连接认证后未实现 RFC 2971 `ID` 扩展指令，网易服务器安全防御规则强制要求客户端 ID 标识，缺省时在 `SELECT INBOX` 阶段直接拒绝返回 `NO ['SELECT Unsafe Login']`。
- 测试缺口：前端单测仅验证 UI 查询重新触发，未断言是否触发后端同步写接口；后端 IMAP 测试仅连接本地离线 Dovecot 夹具（默认不强制校验 ID 命令），缺少针对国内主流邮箱服务扩展要求的真实协议断言。
- 线索：`.scratch/repro_inbox_empty_and_refresh.py`
- 处理：未开
