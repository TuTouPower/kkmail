import { QueryClient } from '@tanstack/react-query'
import { api, type AccountSummary } from './client'
import { mailKey } from '../lib/mailKey'
import { postMailCoreMessageFlag, postMailCoreMessageRead } from './mailCore'

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
  is_flagged?: boolean
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

/** Soft-refresh window: list data stays fresh for 5 minutes, and
 *  invalidateQueries keeps showing the previous payload while refetching.
 *  Soft refresh (toolbar) only marks stale; hard refresh can still `resetQueries`. */
export const MAIL_STALE_TIME_MS = 5 * 60_000

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: MAIL_STALE_TIME_MS,
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
      placeholderData: (previousData: unknown) => previousData,
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

function mapMail(raw: Record<string, unknown>, accountEmail: string, accountId: number | undefined, listFolder: string): MailItem {
  return {
    id: String(raw.id || ''),
    subject: String(raw.subject || '无主题'),
    from: String(raw.from || '未知'),
    to: String(raw.to || ''),
    date: String(raw.date || ''),
    is_read: Boolean(raw.is_read),
    has_attachments: Boolean(raw.has_attachments),
    body_preview: String(raw.body_preview || ''),
    // Always carry a concrete folder: IMAP UIDs are only unique per folder.
    folder: String(raw.folder || (listFolder === 'all' ? 'inbox' : listFolder)),
    id_mode: String(raw.id_mode || ''),
    accountEmail,
    accountId,
  }
}

/** One slow/broken account must not hang the UI forever. */
export const MAIL_FETCH_TIMEOUT_MS = 45_000

export async function fetchEmails(email: string, folder = 'inbox', accountId?: number, signal?: AbortSignal): Promise<MailItem[]> {
  const res = await api.getEmails(email, { folder, top: 40 }, { signal, timeoutMs: MAIL_FETCH_TIMEOUT_MS })
  if (res.success === false) {
    const err = res.error
    const message = typeof err === 'string' ? err : (err as { message?: string } | undefined)?.message || '获取邮件失败'
    throw new Error(message)
  }
  const rows = (res.emails || res.messages || res.items || []) as Record<string, unknown>[]
  return rows.map((row) => mapMail(row, email, accountId, folder))
}

export async function fetchEmailDetail(email: string, messageId: string, folder = 'inbox', idMode = '', signal?: AbortSignal): Promise<MailDetail> {
  const res = await api.getEmailDetail(email, messageId, folder, idMode, { signal, timeoutMs: MAIL_FETCH_TIMEOUT_MS })
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

/** Find a message in any cached list by its mailKey. */
export function findCachedMail(key: string | null): MailItem | undefined {
  if (!key) return undefined
  for (const [, list] of queryClient.getQueriesData<MailItem[]>({ queryKey: ['emails'] })) {
    const hit = (list || []).find((m) => mailKey(m) === key)
    if (hit) return hit
  }
  for (const [, list] of queryClient.getQueriesData<MailItem[]>({ queryKey: ['mail-core', 'inbox'] })) {
    const hit = (list || []).find((m) => mailKey(m) === key)
    if (hit) return hit
  }
  return undefined
}

/** Optimistically update read state in every cached list (inbox, all-inbox, "all" folder). */
export function setCachedReadState(keys: Iterable<string>, isRead: boolean) {
  const wanted = new Set(keys)
  const patch = (list: MailItem[] | undefined) =>
    list?.map((m) => (wanted.has(mailKey(m)) && m.is_read !== isRead ? { ...m, is_read: isRead } : m))
  queryClient.setQueriesData<MailItem[]>({ queryKey: ['emails'] }, patch)
  queryClient.setQueriesData<MailItem[]>({ queryKey: ['mail-core', 'inbox'] }, patch)
}

/** Mark messages read with an optimistic cache update; reverts on failure. */
export async function markReadOptimistic(items: MailItem[]) {
  const unread = items.filter((m) => !m.is_read && m.id)
  if (!unread.length) return
  const keys = unread.map((m) => mailKey(m))
  setCachedReadState(keys, true)

  const mailCoreItems = unread.filter((m) => (m.id_mode || '').includes('mail_core'))
  const flaskItems = unread.filter((m) => !(m.id_mode || '').includes('mail_core'))

  const tasks: Array<{ keys: string[]; run: () => Promise<void> }> = [
    ...mailCoreItems.map((m) => ({
      keys: [mailKey(m)],
      run: async () => {
        await postMailCoreMessageRead(m.id, true)
      },
    })),
  ]
  const byAccount = new Map<string, MailItem[]>()
  flaskItems.forEach((m) => byAccount.set(m.accountEmail, [...(byAccount.get(m.accountEmail) || []), m]))
  for (const [email, list] of byAccount.entries()) {
    tasks.push({
      keys: list.map((m) => mailKey(m)),
      run: async () => {
        const res = await markEmailsRead(email, list, list[0]?.folder || 'inbox')
        if (res && typeof res === 'object' && (res as { success?: boolean }).success === false) {
          const err = (res as { error?: unknown }).error
          throw new Error(
            typeof err === 'string'
              ? err
              : (err as { message?: string } | undefined)?.message || `${email} 标记失败`,
          )
        }
      },
    })
  }

  const results = await Promise.allSettled(tasks.map((t) => t.run()))
  const failedKeys: string[] = []
  const failed: string[] = []
  results.forEach((r, i) => {
    if (r.status === 'rejected') {
      failedKeys.push(...tasks[i].keys)
      failed.push(r.reason instanceof Error ? r.reason.message : String(r.reason))
    }
  })
  if (failedKeys.length) setCachedReadState([...new Set(failedKeys)], false)
  if (failed.length) throw new Error(failed.join('；'))
}

/** Toggle flagged: optimistic local UI then POST mail-core when id_mode is mail_core. */
export async function flagOptimistic(
  item: MailItem,
  nextFlagged: boolean,
  applyLocal: (key: string) => void,
): Promise<void> {
  const key = mailKey(item)
  applyLocal(key)
  if (!(item.id_mode || '').includes('mail_core')) return
  try {
    await postMailCoreMessageFlag(item.id, nextFlagged)
  } catch (err) {
    applyLocal(key) // revert local toggle
    throw err
  }
}
