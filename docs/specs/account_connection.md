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

## Microsoft Graph 浏览器与设备码登录（t055）

- 新增与编辑 Graph 提供浏览器登录、设备码登录及已有命名凭据更新。帮助说明自有 Entra 应用、账号类型、Client ID、Secret value、公共客户端开关和管理员同意条件，不代办注册。
- 浏览器方式使用 PKCE 与可信 Web/桌面回调；微软 Electron 使用 localhost 动态端口，不能套用到 127.0.0.1。设备码无需回调或 Secret，展示官方验证地址、短码、倒计时、复制/打开/取消操作，自动申请后台同步凭据。
- 两种方式均经 Graph `/me` 与邮箱可访问性核实；不解析令牌或从 UPN 猜邮箱。重新授权匹配原邮箱、已存用户 ID、应用和租户，旧 Graph 无用户 ID 可凭精确邮箱建立身份。最终保存沿用共享事务与锁顺序，保留分组/同步偏好/历史邮件。
- 设备码请求与到期轮询均在服务端，原会话带 CSRF 驱动，间隔/限流/取消/过期跨进程串行化；长码不返回前端，期限不超过供应商与本地 10 分钟上限。Microsoft IMAP 继续拒绝。

## 账户接入收敛与锁序（fix/review-20261026-commits，2026-10-26）

- Google 新增账户仅保留 IMAP 应用专用密码路径（p055）：表单只展示邮箱与 16 位应用专用密码，Gmail 连接参数在「高级网络设置」中预置，帮助为开启两步验证、生成应用专用密码、填入表单三步；不再展示 Google Cloud Console / CASA 相关内容。`gmail` 协议与 Gmail API 引擎未下线，已有 Gmail API 账户仍可查看、重新授权与同步；收敛只作用于新增入口，后端经 API 直接创建 `provider=gmail` 仍可达，是否同步封堵留待产品裁决。
- Microsoft 新增账户采用内置公共客户端极简授权（p056，替代上文 t055 所述新增流程；编辑/重新授权仍沿用 t055 的浏览器与设备码流程）：内置公共 Client ID `9e5f94bc-e8a4-4e73-b8be-63364c29d753`（可用环境变量 `MICROSOFT_CLIENT_ID` 覆盖），重定向 URI 固定 `http://localhost:8080`。前端两态表单：发起态打开 Microsoft 授权页；换码态粘贴授权后地址栏完整重定向链接，经 `POST /api/accounts/oauth/exchange-redirect-url` 由服务端无 Secret 换取令牌并以 Graph `/me` 核实真实邮箱。表单邮箱与真实邮箱不一致时以真实邮箱为准建号或更新（refresh token 只属于该身份）。同邮箱已有账户走更新路径并清除旧 `client_secret` 转公共客户端。公共客户端 graph 凭据在连接校验中不再要求 `client_secret`；自备机密应用与 Gmail 的既有校验不变。
- IMAP 登录名渐进披露（p057）：「使用自定义登录名」默认未勾选且不渲染登录名输入框；未勾选时新建不发送 `imap_user`（后端回落邮箱），编辑已存 `imap_user` 的账户发送空串按既有约定清除。编辑 `imap_user` 与邮箱不同的账户自动勾选并回显。
- 账户更新锁序（R16）：`update_account_app` 与 `accounts/service.update_account` 均先无条件获取侧栏组织级 advisory lock，再锁 Account 行，`prior_sync_enabled` 在锁内事务中读取；组织相关路径统一遵循 sidebar → Account → OAuth/凭据 的锁序。
