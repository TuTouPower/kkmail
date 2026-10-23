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
  sort_order?: number
}

export interface MailItem {
  id: string
  subject: string
  from: string
  to?: string
  date?: string | null
  is_read: boolean | null
  is_flagged: boolean | null
  has_attachments: boolean | null
  /** Plain display text: provider snippet or read-only body fallback. */
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
  date?: string | null
  body?: string
  body_type?: 'html' | 'text'
  parse_error?: string | null
  is_archived?: boolean | null
  attachments?: Array<{ id?: string; name?: string; size?: number; contentType?: string }>
  has_attachments?: boolean | null
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
  sidebarLayout: ['sidebar-layout'] as const,
  stats: ['mail-core', 'stats'] as const,
  inbox: (
    accountId: string = ALL_ACCOUNTS,
    filter?: string,
    folderRole: string = 'inbox',
    sortOrder: string = 'desc',
    folderId?: string | null,
    groupId?: string | null,
  ) => {
    const scope = groupId ? `group:${groupId}` : accountScope(accountId)
    const folderPart = folderId ? `folder:${folderId}` : null
    const rolePart = !folderId && folderRole !== 'inbox' ? `role:${folderRole}` : null
    const filterPart = filter && filter !== 'all' ? filter : null
    const sortPart = sortOrder && sortOrder !== 'desc' ? `sort:${sortOrder}` : null

    const key: string[] = ['mail-core', 'inbox', scope]
    if (folderPart) key.push(folderPart)
    if (rolePart) key.push(rolePart)
    if (filterPart) key.push(filterPart)
    if (sortPart) key.push(sortPart)
    return key as unknown as readonly string[]
  },
  search: (q: string, accountId: string = ALL_ACCOUNTS, groupId?: string | null, folderId?: string | null) => {
    const key: string[] = ['mail-core', 'search', groupId ? `group:${groupId}` : accountScope(accountId)]
    if (folderId) key.push(`folder:${folderId}`)
    key.push(q)
    return key as unknown as readonly string[]
  },
}

/** Drop cached group pages when membership changes so no stale members are shown. */
export function resetGroupMailQueries(groupId?: string): Promise<void[]> {
  const scope = groupId ? `group:${groupId}` : null
  const matchesGroupScope = (query: { queryKey: readonly unknown[] }) => {
    const queryScope = query.queryKey[2]
    return typeof queryScope === 'string' && queryScope.startsWith('group:') && (!scope || queryScope === scope)
  }
  return Promise.all([
    queryClient.resetQueries({ queryKey: ['mail-core', 'inbox'], predicate: matchesGroupScope }),
    queryClient.resetQueries({ queryKey: ['mail-core', 'search'], predicate: matchesGroupScope }),
  ])
}

/** Drop all cached list pages after deleting an account. */
export function resetMailListQueries(): Promise<void[]> {
  return Promise.all([
    queryClient.resetQueries({ queryKey: ['mail-core', 'inbox'] }),
    queryClient.resetQueries({ queryKey: ['mail-core', 'search'] }),
  ])
}

export async function fetchGroups(): Promise<GroupItem[]> {
  const res = await api.getGroups()
  return res.groups.map((g) => ({
    id: String(g.id),
    name: g.name,
    color: g.color ?? undefined,
    account_count: g.account_count,
    sort_order: g.sort_order,
  }))
}

const ACCOUNT_PAGE_SIZE = 200

/** Load every account page (limit/offset/has_more). */
export async function fetchAccounts(): Promise<AccountSummary[]> {
  const all: AccountSummary[] = []
  for (;;) {
    const res = await api.getAccounts({ limit: ACCOUNT_PAGE_SIZE, offset: all.length })
    all.push(...res.accounts)
    if (!res.has_more) break
    if (!res.accounts.length) throw new Error('Account pagination returned an empty page while more accounts remain')
  }
  return all
}

function extractItemsFromCache(data: unknown): MailItem[] {
  if (Array.isArray(data)) return data as MailItem[]
  if (data && typeof data === 'object' && 'pages' in data && Array.isArray((data as { pages: unknown[] }).pages)) {
    const pages = (data as { pages: unknown[] }).pages
    const all: MailItem[] = []
    for (const p of pages) {
      if (Array.isArray(p)) {
        all.push(...(p as MailItem[]))
      } else if (p && typeof p === 'object' && 'items' in p && Array.isArray((p as { items: unknown[] }).items)) {
        all.push(...(p as { items: MailItem[] }).items)
      }
    }
    return all
  }
  return []
}

function updateItemsInCache(data: unknown, updater: (items: MailItem[]) => MailItem[]): unknown {
  if (Array.isArray(data)) {
    return updater(data as MailItem[])
  }
  if (data && typeof data === 'object' && 'pages' in data && Array.isArray((data as { pages: unknown[] }).pages)) {
    const inf = data as { pages: unknown[]; pageParams: unknown[] }
    const newPages = inf.pages.map((p) => {
      if (Array.isArray(p)) {
        return updater(p as MailItem[])
      }
      if (p && typeof p === 'object' && 'items' in p && Array.isArray((p as { items: unknown[] }).items)) {
        const pageObj = p as { items: MailItem[]; [key: string]: unknown }
        return {
          ...pageObj,
          items: updater(pageObj.items),
        }
      }
      return p
    })
    return { ...inf, pages: newPages }
  }
  return data
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
    const items = extractItemsFromCache(q.state.data)
    const hit = items.find((m) => mailKey(m) === key)
    if (hit) return hit
  }

  return undefined
}

function patchCachedMail(keys: Iterable<string>, patch: Partial<MailItem>) {
  const wanted = new Set(keys)
  queryClient.setQueriesData({ queryKey: MAIL_LIST_PREFIX }, (oldData) =>
    updateItemsInCache(oldData, (list) =>
      list.map((m) => (wanted.has(mailKey(m)) ? { ...m, ...patch } : m)),
    ),
  )
}

/** Drop messages from every cached list (e.g. after trash). */
export function removeCachedMail(keys: Iterable<string>) {
  const gone = new Set(keys)
  queryClient.setQueriesData({ queryKey: MAIL_LIST_PREFIX }, (oldData) =>
    updateItemsInCache(oldData, (list) => list.filter((m) => !gone.has(mailKey(m)))),
  )
}

export function setCachedReadState(keys: Iterable<string>, isRead: boolean) {
  patchCachedMail(keys, { is_read: isRead })
}

/** Set read status of messages with an optimistic cache update; reverts failures. */
export async function setReadOptimistic(items: MailItem[], nextRead: boolean) {
  const targets = items.filter((m) => m.id).map((item) => {
    const cached = findCachedMail(mailKey(item))
    return cached ? { ...item, is_read: cached.is_read } : item
  }).filter((m) => m.is_read !== nextRead)
  if (!targets.length) return
  setCachedReadState(targets.map(mailKey), nextRead)
  const results = await Promise.allSettled(targets.map((m) => postMailCoreMessageRead(m.id, nextRead)))
  const failed: string[] = []
  results.forEach((r, i) => {
    if (r.status === 'rejected') {
      patchCachedMail([mailKey(targets[i])], { is_read: targets[i].is_read })
      const reason = r.reason as { message?: unknown } | undefined
      failed.push(typeof reason?.message === 'string' ? reason.message : String(r.reason))
    }
  })
  if (failed.length) throw new Error(failed.join('；'))
}

/** Mark messages read with an optimistic cache update; reverts failures. */
export async function markReadOptimistic(items: MailItem[]) {
  return setReadOptimistic(items, true)
}

/** Toggle the server-side flag with an optimistic cache update; restores the prior snapshot on failure. */
export async function flagOptimistic(item: MailItem, nextFlagged: boolean): Promise<void> {
  const key = mailKey(item)
  const cached = findCachedMail(key)
  const priorFlagged = cached ? cached.is_flagged : item.is_flagged
  patchCachedMail([key], { is_flagged: nextFlagged })
  try {
    await postMailCoreMessageFlag(item.id, nextFlagged)
  } catch (err) {
    // Restore the captured prior value — do not blind re-toggle (!nextFlagged).
    patchCachedMail([key], { is_flagged: priorFlagged })
    throw err
  }
}
