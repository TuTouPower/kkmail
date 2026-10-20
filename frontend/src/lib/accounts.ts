import type { AccountSummary } from '../api/client'

/** The backend can only send through Graph-authorised Outlook accounts. */
export function canSendFrom(a?: Pick<AccountSummary, 'account_type'>): boolean {
  return !!a && (a.account_type || 'outlook').toLowerCase() !== 'imap'
}

/** Providers accepted by /api/accounts (keys of MAIL_PROVIDERS on the backend). */
export const IMPORT_PROVIDERS: Array<{ value: string; label: string }> = [
  { value: 'outlook', label: 'Outlook / Graph' },
  { value: 'gmail', label: 'Gmail（IMAP）' },
  { value: 'qq', label: 'QQ 邮箱（IMAP）' },
  { value: '163', label: '网易 163（IMAP）' },
  { value: '126', label: '网易 126（IMAP）' },
  { value: 'yahoo', label: 'Yahoo（IMAP）' },
  { value: 'aliyun', label: '阿里邮箱（IMAP）' },
  { value: 'custom', label: '自定义 IMAP' },
]

/** Accepted line formats per provider, mirroring parse_account_import on the backend. */
export function importFormatHint(provider: string): { placeholder: string; help: string } {
  if (provider === 'outlook') {
    return {
      placeholder: 'user@outlook.com----密码----client_id----refresh_token',
      help: '每行一个账号：邮箱----密码----client_id----refresh_token（密码可留空，四段用 ---- 分隔）。',
    }
  }
  if (provider === 'custom') {
    return {
      placeholder: 'user@example.com----密码----imap.example.com----993',
      help: '每行一个账号：邮箱----密码----IMAP 服务器----端口（端口默认 993，需 SSL/TLS）。',
    }
  }
  return {
    placeholder: 'user@example.com----授权码',
    help: '每行一个账号：邮箱----授权码/应用专用密码。QQ、163、126 需在邮箱设置中开启 IMAP 并生成授权码；Gmail 需使用应用专用密码。',
  }
}
