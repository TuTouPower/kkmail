export type Vendor = 'other' | 'google' | 'microsoft' | 'qq' | 'netease_163' | 'netease_126' | 'netease_yeah' | 'icloud' | 'yahoo' | 'zoho'
export type Protocol = 'imap' | 'graph'
export const vendors: Record<Vendor, { label: string; host: string; credential: string; steps: string[]; url: string }> = {
  other: { label: '其他 / 自定义 IMAP', host: '', credential: '密码或授权码', steps: ['向邮箱管理员获取 IMAP 服务器、端口和登录名。', '使用管理员提供的密码或客户端授权码，默认采用 TLS 993。'], url: '' },
  google: { label: 'Google / Gmail', host: 'imap.gmail.com', credential: '应用专用密码', steps: ['在 Google 账号中开启两步验证（2-Step Verification）。', '打开应用专用密码页面：https://myaccount.google.com/apppasswords', '生成 16 位应用专用密码，并粘贴到 kkmail 的密码框中。普通 Google 登录密码不能使用。'], url: 'https://myaccount.google.com/apppasswords' },
  microsoft: { label: 'Microsoft / Outlook / Microsoft 365', host: '', credential: '', steps: [
    '点击「微软授权登录」，在打开的微软页面登录 Outlook / Microsoft 365 账号并同意授权。',
    '授权完成后，浏览器会跳转到一个打不开的 localhost 地址，复制地址栏中的完整网址。',
    '把完整网址粘贴回 kkmail 的输入框，点击「换取 Token 并添加」即可完成添加；无需注册 Azure 应用，也无需填写 Client Secret。',
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
export const defaultProtocol = (vendor: Vendor): Protocol => vendor === 'microsoft' ? 'graph' : 'imap'

// p056: Microsoft simplified onboarding uses the built-in public client
// (mirrors DEFAULT_MICROSOFT_CLIENT_ID / DEFAULT_MICROSOFT_REDIRECT_URI in
// mail_core/accounts/microsoft_oauth.py). Public clients have no secret.
export const MICROSOFT_PUBLIC_CLIENT_ID = '9e5f94bc-e8a4-4e73-b8be-63364c29d753'
export const MICROSOFT_DEFAULT_REDIRECT_URI = 'http://localhost:8080'
export const MICROSOFT_GRAPH_SCOPES = 'https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read offline_access'

export function buildMicrosoftAuthorizeUrl(opts: { clientId?: string; redirectUri?: string; email?: string; state?: string } = {}): string {
  const state = opts.state || (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`)
  const params = new URLSearchParams({
    client_id: opts.clientId?.trim() || MICROSOFT_PUBLIC_CLIENT_ID,
    response_type: 'code',
    redirect_uri: opts.redirectUri?.trim() || MICROSOFT_DEFAULT_REDIRECT_URI,
    response_mode: 'query',
    scope: MICROSOFT_GRAPH_SCOPES,
    state,
    prompt: 'select_account',
  })
  const hint = opts.email?.trim()
  if (hint) params.set('login_hint', hint)
  return `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?${params.toString()}`
}
