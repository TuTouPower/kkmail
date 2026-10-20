import { QueryClient } from '@tanstack/react-query'
import { api, type AccountSummary } from './client'

export interface GroupItem {
  id: number
  name: string
  color?: string
  account_count?: number
  descendant_account_count?: number
  parent_id?: number | null
  level?: number
}

export interface MailItem {
  id: string
  subject: string
  from: string
  to?: string
  date?: string
  is_read: boolean
  has_attachments: boolean
  body_preview?: string
  folder?: string
  id_mode?: string
  accountEmail: string
  accountId?: number
}

export interface MailDetail {
  id?: string
  subject?: string
  from?: string
  to?: string
  cc?: string
  date?: string
  body?: string
  body_type?: string
  attachments?: Array<{ id?: string; name?: string; size?: number; contentType?: string }>
  has_attachments?: boolean
  folder?: string
  id_mode?: string
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
      refetchOnWindowFocus: false,
    },
  },
})

export const queryKeys = {
  groups: ['groups'] as const,
  accounts: ['accounts'] as const,
  emails: (email: string, folder: string) => ['emails', email, folder] as const,
  detail: (email: string, id: string, folder: string, idMode: string) => ['detail', email, id, folder, idMode] as const,
}

export async function fetchGroups(): Promise<GroupItem[]> {
  const res = await api.getGroups()
  return (res.groups as GroupItem[]) || []
}

const ACCOUNT_PAGE_SIZE = 200
const ACCOUNT_MAX_PAGES = 100

/** Load every account page; the backend paginates with limit/offset/has_more. */
export async function fetchAccounts(): Promise<AccountSummary[]> {
  const all: AccountSummary[] = []
  for (let page = 0; page < ACCOUNT_MAX_PAGES; page++) {
    const res = await api.getAccounts({ limit: ACCOUNT_PAGE_SIZE, offset: all.length })
    if (res.success === false) throw new Error('获取账户失败')
    const rows = res.accounts || res.items || []
    all.push(...rows)
    const total = typeof res.total === 'number' ? res.total : undefined
    if (!rows.length || res.has_more === false || (total !== undefined && all.length >= total)) break
    if (res.has_more === undefined && total === undefined && rows.length < ACCOUNT_PAGE_SIZE) break
  }
  return all
}

/** The unified inbox fans out one request per account, so it is capped. */
export const ALL_INBOX_ACCOUNT_LIMIT = 8

function mapMail(raw: Record<string, unknown>, accountEmail: string, accountId?: number): MailItem {
  return {
    id: String(raw.id || ''),
    subject: String(raw.subject || '无主题'),
    from: String(raw.from || '未知'),
    to: String(raw.to || ''),
    date: String(raw.date || ''),
    is_read: Boolean(raw.is_read),
    has_attachments: Boolean(raw.has_attachments),
    body_preview: String(raw.body_preview || ''),
    folder: String(raw.folder || ''),
    id_mode: String(raw.id_mode || ''),
    accountEmail,
    accountId,
  }
}

export async function fetchEmails(email: string, folder = 'inbox', accountId?: number): Promise<MailItem[]> {
  const res = await api.getEmails(email, { folder, top: 40 })
  if (res.success === false) {
    const err = res.error
    const message = typeof err === 'string' ? err : (err as { message?: string } | undefined)?.message || '获取邮件失败'
    throw new Error(message)
  }
  const rows = (res.emails || res.messages || res.items || []) as Record<string, unknown>[]
  return rows.map((row) => mapMail(row, email, accountId))
}

export async function fetchEmailDetail(email: string, messageId: string, folder = 'inbox', idMode = ''): Promise<MailDetail> {
  const res = await api.getEmailDetail(email, messageId, folder, idMode)
  if (res.success === false) {
    const err = res.error
    const message = typeof err === 'string' ? err : (err as { message?: string } | undefined)?.message || '获取邮件详情失败'
    throw new Error(message)
  }
  return (res.email as MailDetail) || {}
}

export async function markEmailsRead(email: string, items: Array<{ id: string; folder?: string; id_mode?: string }>, folder = 'inbox') {
  return api.markRead({
    email,
    folder,
    method: 'graph',
    items: items.map((item) => ({
      id: item.id,
      folder: item.folder || folder,
      id_mode: item.id_mode || '',
    })),
  })
}
