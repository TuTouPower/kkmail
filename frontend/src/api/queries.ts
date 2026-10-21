import { QueryClient } from '@tanstack/react-query'
import { api, type AccountSummary } from './client'
import { mailKey } from '../lib/mailKey'
import { postMailCoreMessageFlag, postMailCoreMessageRead } from './mailCore'
import { useMailStore } from '../store/mailStore'

export interface GroupItem {
  id: string
  name: string
  color?: string
  account_count?: number
}

export interface MailItem {
  id: string
  subject: string
  from: string
  to?: string
  date?: string
  is_read: boolean
  is_flagged: boolean
  has_attachments: boolean
  body_preview?: string
  folder?: string
  accountEmail: string
  /** mail-core account UUID */
  accountId?: string
}

export interface MailDetail {
  id?: string
  subject?: string
  from?: string
  to?: string
  cc?: string
  date?: string
  body?: string
  body_type?: 'html' | 'text'
  attachments?: Array<{ id?: string; name?: string; size?: number; contentType?: string }>
  has_attachments?: boolean
}

/** Lists stay fresh for 5 minutes; SSE events invalidate earlier. */
export const MAIL_STALE_TIME_MS = 5 * 60_000

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: MAIL_STALE_TIME_MS,
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
      // Intentionally no global placeholderData — detail queries must not show the previous message.
    },
  },
})

/** Every cached message list lives under this prefix (inbox + search). */
export const MAIL_LIST_PREFIX = ['mail-core'] as const

/**
 * Query-key scope for the unified inbox. Reserved so it cannot collide with a
 * real account UUID (or the literal string "all").
 */
export const ALL_ACCOUNTS = '__all__' as const

/** Normalize an optional account id into a query-key scope segment. */
export function accountScope(accountId?: string | null): string {
  const id = typeof accountId === 'string' ? accountId.trim() : ''
  return id || ALL_ACCOUNTS
}

export const queryKeys = {
  groups: ['groups'] as const,
  accounts: ['accounts'] as const,
  stats: ['mail-core', 'stats'] as const,
  inbox: (accountId: string = ALL_ACCOUNTS) => ['mail-core', 'inbox', accountScope(accountId)] as const,
  search: (q: string, accountId: string = ALL_ACCOUNTS) => ['mail-core', 'search', accountScope(accountId), q] as const,
}

export async function fetchGroups(): Promise<GroupItem[]> {
  const res = await api.getGroups()
  return res.groups.map((g) => ({
    id: String(g.id),
    name: g.name,
    color: g.color ?? undefined,
    account_count: g.account_count,
  }))
}

const ACCOUNT_PAGE_SIZE = 200
const ACCOUNT_MAX_PAGES = 100

/** Load every account page (limit/offset/has_more). */
export async function fetchAccounts(): Promise<AccountSummary[]> {
  const all: AccountSummary[] = []
  for (let page = 0; page < ACCOUNT_MAX_PAGES; page++) {
    const res = await api.getAccounts({ limit: ACCOUNT_PAGE_SIZE, offset: all.length })
    all.push(...res.accounts)
    if (!res.accounts.length || !res.has_more) break
  }
  return all
}

/** Find a message in cached lists by its mailKey, prioritizing current view and latest updated lists. */
export function findCachedMail(key: string | null): MailItem | undefined {
  if (!key) return undefined

  let currentScope: string | undefined
  try {
    const view = useMailStore.getState().view
    const accountId = view.type === 'account' ? view.accountId : undefined
    currentScope = accountScope(accountId)
  } catch {
    /* ignore if outside react/store */
  }

  const queries = queryClient.getQueryCache().findAll({ queryKey: MAIL_LIST_PREFIX })
  const sorted = [...queries].sort((a, b) => {
    const aCurrent = currentScope ? a.queryKey.includes(currentScope) : false
    const bCurrent = currentScope ? b.queryKey.includes(currentScope) : false
    if (aCurrent && !bCurrent) return -1
    if (!aCurrent && bCurrent) return 1
    return (b.state.dataUpdatedAt || 0) - (a.state.dataUpdatedAt || 0)
  })

  for (const q of sorted) {
    const list = q.state.data as MailItem[] | undefined
    if (Array.isArray(list)) {
      const hit = list.find((m) => mailKey(m) === key)
      if (hit) return hit
    }
  }

  return undefined
}

function patchCachedMail(keys: Iterable<string>, patch: Partial<MailItem>) {
  const wanted = new Set(keys)
  queryClient.setQueriesData<MailItem[]>({ queryKey: MAIL_LIST_PREFIX }, (list) =>
    list?.map((m) => (wanted.has(mailKey(m)) ? { ...m, ...patch } : m)),
  )
}

/** Drop messages from every cached list (e.g. after trash). */
export function removeCachedMail(keys: Iterable<string>) {
  const gone = new Set(keys)
  queryClient.setQueriesData<MailItem[]>({ queryKey: MAIL_LIST_PREFIX }, (list) => list?.filter((m) => !gone.has(mailKey(m))))
}

export function setCachedReadState(keys: Iterable<string>, isRead: boolean) {
  patchCachedMail(keys, { is_read: isRead })
}

/** Mark messages read with an optimistic cache update; reverts failures. */
export async function markReadOptimistic(items: MailItem[]) {
  const unread = items.filter((m) => !m.is_read && m.id)
  if (!unread.length) return
  setCachedReadState(unread.map(mailKey), true)
  const results = await Promise.allSettled(unread.map((m) => postMailCoreMessageRead(m.id, true)))
  const failedKeys: string[] = []
  const failed: string[] = []
  results.forEach((r, i) => {
    if (r.status === 'rejected') {
      failedKeys.push(mailKey(unread[i]))
      const reason = r.reason as { message?: unknown } | undefined
      failed.push(typeof reason?.message === 'string' ? reason.message : String(r.reason))
    }
  })
  if (failedKeys.length) setCachedReadState(failedKeys, false)
  if (failed.length) throw new Error(failed.join('；'))
}

/** Toggle the server-side flag with an optimistic cache update; restores the prior snapshot on failure. */
export async function flagOptimistic(item: MailItem, nextFlagged: boolean): Promise<void> {
  const key = mailKey(item)
  const cached = findCachedMail(key)
  const priorFlagged = cached?.is_flagged ?? item.is_flagged
  patchCachedMail([key], { is_flagged: nextFlagged })
  try {
    await postMailCoreMessageFlag(item.id, nextFlagged)
  } catch (err) {
    // Restore the captured prior value — do not blind re-toggle (!nextFlagged).
    patchCachedMail([key], { is_flagged: priorFlagged })
    throw err
  }
}
