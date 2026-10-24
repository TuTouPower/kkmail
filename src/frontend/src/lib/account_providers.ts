export type Vendor = 'other' | 'google' | 'microsoft' | 'qq' | 'netease_163' | 'netease_126' | 'netease_yeah' | 'icloud' | 'yahoo' | 'zoho'
export type Protocol = 'imap' | 'gmail' | 'graph'
export const vendors: Record<Vendor, { label: string; host: string; credential: string; steps: string[]; url: string }> = {
  other: { label: '其他 / 自定义 IMAP', host: '', credential: '密码或授权码', steps: ['向邮箱管理员获取 IMAP 服务器、端口和登录名。', '使用管理员提供的密码或客户端授权码，默认采用 TLS 993。'], url: '' },
  google: { label: 'Google / Gmail', host: 'imap.gmail.com', credential: '应用专用密码', steps: ['IMAP：先在 Google 账号安全设置启用两步验证，再生成应用专用密码，填写到密码框。普通 Google 登录密码不能使用。', 'Gmail API 权限使用 gmail.modify；该范围包含供应商定义的发送能力，本产品不提供发信，也不额外申请 gmail.send 或 https://mail.google.com/ 全量权限。', 'OAuth：在 Google Cloud 启用 Gmail API，配置同意屏幕、测试用户及 OAuth 客户端。自托管网页使用 Web 应用（机密客户端，需配置 Client Secret 并登记表单显示的固定 HTTPS 回调地址），Electron 桌面端使用桌面应用（Desktop app 公共客户端，采用 127.0.0.1 动态端口 loopback 回调），回调地址必须匹配。', '个人部署也需自有 Google 应用配置，授权按钮不会代办注册或应用验证。点击登录或重新授权完成后，返回窗口保存即可自动保存凭据并继续后台同步。测试模式的 Gmail 授权常见 7 天到期；组织策略或高级保护可能禁止应用密码。个人 Gmail 的 IMAP 默认开启。'], url: 'https://support.google.com/accounts/answer/185833' },
  microsoft: { label: 'Microsoft / Outlook / Microsoft 365', host: '', credential: '', steps: [
    '在 Microsoft Entra ID → App registrations → New registration 注册自有应用，选择包含目标个人 Outlook/Hotmail/Live 或 Microsoft 365 组织账号的账号类型。Overview 复制 Application (client) ID。同一 Client ID 标识应用，可供多个邮箱授权。',
    '应用注册需要可用 Entra 租户及注册权限，不能保证每个个人微软账号都能自行注册。组织可能要求管理员同意；应用不会代办注册或绕过策略。',
    '浏览器登录与熟悉的 Google 登录相似：填写应用配置 → 打开微软登录页 → 同意 → 返回 kkmail 保存。自托管网页登记 Web 类型的表单 HTTPS 回调，并提供 Secret value；不要登记 SPA 类型，因为换码发生在后端。',
    'Electron 使用移动和桌面应用的 localhost loopback 回调。微软仅对 localhost 忽略动态端口，路径仍须匹配；127.0.0.1 不享受此端口规则，不能套用 Google 设置。按表单实际地址登记 localhost 路径，不需要固定本地端口。',
    '设备码登录：Authentication → Advanced settings → Allow public client flows 设为 Yes。无需回调地址或 Client Secret。回到 kkmail 选择设备码登录 → 复制短验证码 → 打开微软官方验证页 → 输入代码并登录 → 返回 kkmail 等待确认并保存。',
    'API permissions 添加 Microsoft Graph 委托 Mail.ReadWrite、User.Read；User.Read 用于核对当前用户与邮箱，不申请 Mail.Send 或 IMAP 权限。两种方式均自动申请 offline_access（允许后台继续同步），无需另外勾选、填写或购买。',
    '仅 Web 机密客户端创建并复制 Client Secret 的 value；secret ID 不是密钥。Refresh Token 由本产品完成登录后自动获取，不能在门户直接查看。已有合法 Refresh Token 可在高级命名字段更新，但必须匹配原应用、租户及邮件权限；不提供抓包或第三方 Token 工具步骤。',
  ], url: 'https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app' },
  qq: { label: 'QQ / Foxmail 邮箱', host: 'imap.qq.com', credential: '客户端授权码', steps: ['登录 QQ 邮箱网页版，进入设置 → 账号，开启 IMAP 服务。', '生成客户端授权码，填写到授权码框。使用完整邮箱地址作为登录名；不是 QQ 登录密码。'], url: 'https://service.mail.qq.com/detail/0/141' },
  netease_163: { label: '网易 163', host: 'imap.163.com', credential: '客户端授权码', steps: ['登录网易邮箱网页版 → 设置 → POP3/SMTP/IMAP，开启 IMAP 客户端协议。', '新增通用客户端授权码并保存，填写到授权码框。'], url: 'https://help.mail.163.com/faq.do?m=list&categoryID=90' },
  netease_126: { label: '网易 126', host: 'imap.126.com', credential: '客户端授权码', steps: ['登录网易邮箱网页版 → 设置 → POP3/SMTP/IMAP，开启 IMAP 客户端协议。', '新增通用客户端授权码并保存，填写到授权码框。'], url: 'https://help.mail.163.com/faq.do?m=list&categoryID=90' },
  netease_yeah: { label: '网易 yeah', host: 'imap.yeah.net', credential: '客户端授权码', steps: ['登录网易邮箱网页版 → 设置 → POP3/SMTP/IMAP，开启 IMAP 客户端协议。', '新增通用客户端授权码并保存，填写到授权码框。'], url: 'https://help.mail.163.com/faq.do?m=list&categoryID=90' },
  icloud: { label: 'iCloud', host: 'imap.mail.me.com', credential: '应用专用密码', steps: ['Apple 账号须启用双重认证，在账号安全设置生成应用专用密码。', 'IMAP 登录名通常可用邮箱前缀，连接失败时使用完整邮箱地址。'], url: 'https://support.apple.com/en-us/102525' },
  yahoo: { label: 'Yahoo', host: 'imap.mail.yahoo.com', credential: '应用专用密码', steps: ['在 Yahoo 账号安全设置生成 App Password，使用完整邮箱登录名。', '应用密码可用性受账号安全策略限制。'], url: 'https://in.help.yahoo.com/kb/SLN4075.html' },
  zoho: { label: 'Zoho', host: 'imap.zoho.com', credential: '密码或应用专用密码', steps: ['先在 Zoho 邮箱账户设置启用 IMAP；部分免费计划或管理员策略禁止 IMAP。', '个人常用 imap.zoho.com，付费企业常用 imappro.zoho.com，实际服务器以账号内数据中心配置为准。', '启用两步验证或 SAML 登录时生成并使用应用专用密码。'], url: 'https://www.zoho.com/mail/help/imap-access.html' },
}
const domains: Record<string, Vendor> = { 'gmail.com': 'google', 'googlemail.com': 'google', 'outlook.com': 'microsoft', 'outlook.cn': 'microsoft', 'hotmail.com': 'microsoft', 'live.com': 'microsoft', 'msn.com': 'microsoft', 'hotmail.co.uk': 'microsoft', 'live.co.uk': 'microsoft', 'hotmail.fr': 'microsoft', 'live.fr': 'microsoft', 'hotmail.de': 'microsoft', 'live.de': 'microsoft', 'outlook.de': 'microsoft', 'qq.com': 'qq', 'foxmail.com': 'qq', '163.com': 'netease_163', '126.com': 'netease_126', 'yeah.net': 'netease_yeah', 'icloud.com': 'icloud', 'me.com': 'icloud', 'mac.com': 'icloud', 'yahoo.com': 'yahoo', 'yahoo.co.uk': 'yahoo', 'zoho.com': 'zoho', 'zohomail.com': 'zoho' }
export const inferVendor = (email: string): Vendor => domains[email.trim().toLowerCase().split('@')[1]] || 'other'
export const defaultProtocol = (vendor: Vendor): Protocol => vendor === 'google' ? 'gmail' : vendor === 'microsoft' ? 'graph' : 'imap'
