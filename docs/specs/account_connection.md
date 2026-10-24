# 账户连接与供应商设置

## 生效行为（t053）

- 添加与编辑按供应商展示连接方式、独立命名凭据字段和帮助图标；帮助弹窗关闭后恢复触发点焦点并保留草稿。
- Google 支持 Gmail API OAuth 与 IMAP 应用专用密码；Microsoft 仅 Graph OAuth，禁止可识别 Microsoft IMAP 接入。QQ/Foxmail、网易、iCloud、Yahoo、Zoho 提供 IMAP 预设与官方帮助，其他供应商保留自定义配置。
- 编辑保留原服务器、端口、TLS、登录名和协议；不按域名猜测改写既有配置。凭据不回显，空字段保留原值，非空凭据按字段合并。OAuth 凭据变更清除旧 Access Token，编辑与刷新通过加密行锁防止令牌轮换丢失。
- 当前实例不存在 Microsoft IMAP，未增加跨协议邮件身份迁移。成功保存不表示已经验证远端连接。

## Google OAuth 跳转回调与重新授权（t054）

- Google 新增账户提供“使用 Google 登录”，编辑既有 Gmail API 账户提供“重新授权”，同时保留 Google IMAP 应用专用密码路径与已有 OAuth 凭据手动更新。
- 短期 OAuth 授权流程（`oauth_flow.py` + `oauth_routes.py`）使用 `response_type=code`、PKCE `S256`、`access_type=offline`、`prompt=consent`，仅申请 `https://www.googleapis.com/auth/gmail.modify`。流程加密保存在 `CredentialSecret`（跨进程共享并通过 `credential_edit` 行锁串行化），绑定发起会话身份（`session_key`）与 `session_epoch`，有效期 10 分钟。
- 自托管网页模式使用可信部署配置 `MAIL_CORE_PUBLIC_ORIGIN` 生成固定 HTTPS 回调 URI（机密客户端），绝不信任请求 `Host`/`Forwarded` 或 URL 查询参数；Electron 桌面端（`KKMAIL_SIDECAR=1`）使用 `http://127.0.0.1:{MAIL_CORE_PORT}/api/accounts/oauth/callback/google` 动态端口 loopback 回调（公共客户端）。
- 回调端点允许无应用 Cookie 的桌面系统浏览器访问，原子消费 `state` 与 `code`，调用 Google token 端点换码并调用 Gmail `users.getProfile` 核实真实邮箱。回调仅暂存结果，不直接新增或修改账户；只有原始登录会话点击最终“添加 / 保存修改”时才在同一事务内原子写入账户与加密凭据并销毁一次性授权结果。
- 回调响应设置 `Cache-Control: no-store`、`Referrer-Policy: no-referrer` 与无外链 CSP，内联脚本通过 `history.replaceState` 清理地址栏查询字符串；日志自动脱敏回调查询参数与短期验证秘密。
