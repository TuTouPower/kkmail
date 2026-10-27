import { QueryClient } from '@tanstack/react-query'
import { api, type AccountSummary } from './client'
import { logDiagnostic } from '../lib/diagnostics'
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
  locations?: Array<{ folder_id: string; role: string }>
}

export interface MailDetail {
  id?: string
  subject?: string
  from?: string
  fromAddress?: string
  fromName?: string | null
  to?: string
  cc?: string
  toAddresses?: Array<{ name: string | null; address: string | null; text?: string | null }>
  ccAddresses?: Array<{ name: string | null; address: string | null; text?: string | null }>
  date?: string | null
  body?: string
  body_type?: 'html' | 'text'
  parse_error?: string | null
  is_archived?: boolean | null
  archive_state?: string | null
  archive_has_error?: boolean
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

/** Predicate matching only mail list and search query keys under mail-core. */
export function isMailListQueryKey(key: unknown): boolean {
  return Array.isArray(key) && key.length >= 2 && key[0] === 'mail-core' && (key[1] === 'inbox' || key[1] === 'search')
}

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
  settings: ['settings'] as const,
  stats: ['mail-core', 'stats'] as const,
  /**
   * Sidebar stats are computed over the enabled-account set, so the key
   * carries a digest of that set (A19): when membership changes, the stats
   * query gets a fresh key and refetches instead of serving numbers computed
   * over the old membership captured by the queryFn closure.
   */
  statsForAccounts: (accountIds: readonly string[]) =>
    ['mail-core', 'stats', [...accountIds].sort().join(',')] as const,
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
/** 50 pages × 200 = 10,000 accounts — a ceiling matched to the product scale (A91). */
const ACCOUNT_MAX_PAGES = 50

/** Load every account page (limit/offset/has_more). */
export async function fetchAccounts(): Promise<AccountSummary[]> {
  const all: AccountSummary[] = []
  let offset = 0
  for (let page = 0; page < ACCOUNT_MAX_PAGES; page += 1) {
    const res = await api.getAccounts({ limit: ACCOUNT_PAGE_SIZE, offset })
    if (!Number.isSafeInteger(res.total) || res.total < 0) {
      throw new Error('Account pagination returned an invalid total')
    }
    if (res.offset !== offset) {
      throw new Error('Account pagination returned an unexpected offset')
    }
    all.push(...res.accounts)
    if (all.length >= res.total) return all.slice(0, res.total)
    if (!res.has_more) return all
    if (!res.accounts.length) throw new Error('Account pagination returned an empty page while more accounts remain')
    const nextOffset = offset + res.accounts.length
    if (!Number.isSafeInteger(nextOffset) || nextOffset <= offset) {
      throw new Error('Account pagination offset did not advance')
    }
    offset = nextOffset
  }
  // A backend that keeps claiming has_more must not amplify into a request
  // storm: degrade to the accounts collected so far and leave a diagnostic
  // trail instead of failing the whole accounts view (A91).
  logDiagnostic('warn', 'api', 'Account pagination exceeded the page cap; returning the accounts collected so far', {
    pages: ACCOUNT_MAX_PAGES,
    collected: all.length,
  })
  return all
}

function extractItemsFromCache(data: unknown): MailItem[] {
  const isValidMailItem = (item: unknown): item is MailItem =>
    Boolean(item && typeof item === 'object' && typeof (item as MailItem).id === 'string' && (item as MailItem).id.trim())

  if (Array.isArray(data)) return data.filter(isValidMailItem)
  if (data && typeof data === 'object' && 'pages' in data && Array.isArray((data as { pages: unknown[] }).pages)) {
    const pages = (data as { pages: unknown[] }).pages
    const all: MailItem[] = []
    for (const p of pages) {
      if (Array.isArray(p)) {
        all.push(...p.filter(isValidMailItem))
      } else if (p && typeof p === 'object' && 'items' in p && Array.isArray((p as { items: unknown[] }).items)) {
        all.push(...(p as { items: unknown[] }).items.filter(isValidMailItem))
      }
    }
    return all
  }
  if (data && typeof data === 'object' && 'items' in data && Array.isArray((data as { items: unknown[] }).items)) {
    return (data as { items: unknown[] }).items.filter(isValidMailItem)
  }
  return []
}

function updateItemsInCache(data: unknown, updater: (items: MailItem[]) => MailItem[]): unknown {
  const isValidMailItem = (item: unknown): item is MailItem =>
    Boolean(item && typeof item === 'object' && typeof (item as MailItem).id === 'string' && (item as MailItem).id.trim())

  if (Array.isArray(data)) {
    if (data.length > 0 && !data.every(isValidMailItem)) return data
    return updater(data as MailItem[])
  }
  if (data && typeof data === 'object' && 'pages' in data && Array.isArray((data as { pages: unknown[] }).pages)) {
    const inf = data as { pages: unknown[]; pageParams: unknown[] }
    const newPages = inf.pages.map((p) => {
      if (Array.isArray(p)) {
        if (p.length > 0 && !p.every(isValidMailItem)) return p
        return updater(p as MailItem[])
      }
      if (p && typeof p === 'object' && 'items' in p && Array.isArray((p as { items: unknown[] }).items)) {
        const pageObj = p as { items: unknown[]; [key: string]: unknown }
        if (pageObj.items.length > 0 && !pageObj.items.every(isValidMailItem)) return p
        return {
          ...pageObj,
          items: updater(pageObj.items as MailItem[]),
        }
      }
      return p
    })
    return { ...inf, pages: newPages }
  }
  if (data && typeof data === 'object' && 'items' in data && Array.isArray((data as { items: unknown[] }).items)) {
    const page = data as { items: unknown[]; [key: string]: unknown }
    if (page.items.length > 0 && !page.items.every(isValidMailItem)) return data
    return { ...page, items: updater(page.items as MailItem[]) }
  }
  return data
}

function orderedMailListQueries() {
  let currentScope: string | undefined
  try {
    const view = useMailStore.getState().view
    if (view.type === 'group' && view.groupId) {
      currentScope = `group:${view.groupId}`
    } else if (view.type === 'account' && view.accountId) {
      currentScope = accountScope(view.accountId)
    } else if (view.type === 'folder' && view.accountId) {
      currentScope = accountScope(view.accountId)
    } else if (view.type === 'favorite' && view.accountId) {
      currentScope = accountScope(view.accountId)
    } else {
      currentScope = ALL_ACCOUNTS
    }
  } catch {
    /* ignore if outside react/store */
  }

  const queries = queryClient.getQueryCache().findAll({ predicate: (query) => isMailListQueryKey(query.queryKey) })
  return [...queries].sort((a, b) => {
    const aCurrent = currentScope ? a.queryKey.includes(currentScope) : false
    const bCurrent = currentScope ? b.queryKey.includes(currentScope) : false
    if (aCurrent && !bCurrent) return -1
    if (!aCurrent && bCurrent) return 1
    return (b.state.dataUpdatedAt || 0) - (a.state.dataUpdatedAt || 0)
  })
}

function buildCachedMailIndex(): Map<string, MailItem> {
  const index = new Map<string, MailItem>()
  for (const query of orderedMailListQueries()) {
    for (const mail of extractItemsFromCache(query.state.data)) {
      const key = mailKey(mail)
      if (!index.has(key)) index.set(key, mail)
    }
  }
  return index
}

/** Find a message in cached lists by its mailKey, prioritizing current view and latest updated lists. */
export function findCachedMail(key: string | null): MailItem | undefined {
  if (!key) return undefined

  for (const q of orderedMailListQueries()) {
    const items = extractItemsFromCache(q.state.data)
    const hit = items.find((m) => m && typeof m.id === 'string' && m.id.trim() && mailKey(m) === key)
    if (hit) return hit
  }

  return undefined
}

function patchCachedMail(keys: Iterable<string>, patch: Partial<MailItem>) {
  const wanted = new Set(keys)
  queryClient.setQueriesData({ predicate: (query) => isMailListQueryKey(query.queryKey) }, (oldData) =>
    updateItemsInCache(oldData, (list) =>
      list.map((m) => (m && typeof m.id === 'string' && m.id.trim() && wanted.has(mailKey(m)) ? { ...m, ...patch } : m)),
    ),
  )
}

function readStatesForKeys(keys: Iterable<string>): Map<string, Array<MailItem['is_read']>> {
  const wanted = new Set(keys)
  const states = new Map<string, Array<MailItem['is_read']>>()
  for (const query of queryClient.getQueryCache().findAll({ predicate: (item) => isMailListQueryKey(item.queryKey) })) {
    for (const mail of extractItemsFromCache(query.state.data)) {
      const key = mailKey(mail)
      if (!wanted.has(key)) continue
      const values = states.get(key) || []
      values.push(mail.is_read)
      states.set(key, values)
    }
  }
  return states
}

/** Drop messages from every cached list (e.g. after trash). */
export function removeCachedMail(keys: Iterable<string>) {
  const gone = new Set(keys)
  queryClient.setQueriesData({ predicate: (query) => isMailListQueryKey(query.queryKey) }, (oldData) =>
    updateItemsInCache(oldData, (list) => list.filter((m) => !m || typeof m.id !== 'string' || !m.id.trim() || !gone.has(mailKey(m)))),
  )
}

export function setCachedReadState(keys: Iterable<string>, isRead: boolean) {
  setReadStateCache(keys, isRead, true)
}

/** Set read status of messages with an optimistic cache update; reverts failures. */
const READ_MUTATION_BATCH_SIZE = 50

type ReadStatus = MailItem['is_read']
type SidebarStatsCache = { totalUnread: number | null; byAccount: Map<string, number | null> }

const readOperationRevisions = new Map<string, number>()
const pendingReadRequests = new Map<string, Promise<void>>()
let pendingReadMutationCount = 0
let readPreparationTail: Promise<void> = Promise.resolve()
let deferredListInvalidation = false
let deferredStatsInvalidation = false
let readRefreshInFlight = false
let readRefreshPromise: Promise<void> | null = null
let activeSingleReadCount = 0
let singleReadDrain: Promise<void> | null = null
let resolveSingleReadDrain: (() => void) | null = null
let bulkReadRequested = false
let bulkReadInFlight = false
let bulkReadGate: Promise<void> | null = null
let resolveBulkReadGate: (() => void) | null = null

function readStateDelta(previous: ReadStatus, next: ReadStatus): number {
  if (previous === false && next) return -1
  if (previous === true && !next) return 1
  return 0
}

function incrementKnownUnread(value: number | null | undefined, delta: number): number | null | undefined {
  return typeof value === 'number' ? Math.max(0, value + delta) : value
}

function updateCachedReadStatistics(item: MailItem, previous: ReadStatus, next: ReadStatus) {
  const delta = readStateDelta(previous, next)
  if (!delta || !item.accountId) return
  const enabledAndGroup = queryClient.getQueryData<AccountSummary[]>(queryKeys.accounts)?.find((account) => account.id === item.accountId)
  const accountEnabled = enabledAndGroup?.sync_enabled !== false
  const locations = item.locations || []
  const inboxLocations = locations.filter((location) => location.role === 'inbox').length
  if (accountEnabled && inboxLocations) {
    // Prefix-matched update: the live stats entry lives under the
    // account-set digest key (queryKeys.statsForAccounts, A19), not the
    // bare stats key.
    queryClient.setQueriesData<SidebarStatsCache>({ queryKey: queryKeys.stats }, (old) => {
      if (!old) return old
      const accountUnread = old.byAccount.get(item.accountId!)
      if (typeof accountUnread !== 'number') return old
      const byAccount = new Map(old.byAccount)
      byAccount.set(item.accountId!, Math.max(0, accountUnread + delta * inboxLocations))
      return {
        ...old,
        totalUnread: incrementKnownUnread(old.totalUnread, delta * inboxLocations) ?? null,
        byAccount,
      }
    })
  }

  const scopes = [`account:${item.accountId}`]
  if (accountEnabled) {
    scopes.unshift('all')
    if (enabledAndGroup?.group_id) scopes.push(`group:${enabledAndGroup.group_id}`)
  }
  for (const location of locations) {
    for (const scope of scopes) {
      for (const folderId of ['', location.folder_id]) {
        const key = ['mail-core', 'folder-stats', scope, location.role, folderId] as const
        queryClient.setQueryData<{ total: number | null; unread: number | null }>(key, (old) => {
          if (!old) return old
          const unread = incrementKnownUnread(old.unread, delta)
          return unread === old.unread ? old : { ...old, unread: unread ?? null }
        })
      }
    }
  }

  queryClient.setQueryData<Array<{ folder_id: string; role: string; unread_count: number | null }>>(
    ['mail-core', 'account-folders', item.accountId],
    (old) => {
      if (!old) return old
      let changed = false
      const folders = old.map((folder) => {
        const locationCount = locations.filter((location) => location.folder_id === folder.folder_id).length
        if (!locationCount || typeof folder.unread_count !== 'number') return folder
        changed = true
        return { ...folder, unread_count: Math.max(0, folder.unread_count + delta * locationCount) }
      })
      return changed ? folders : old
    },
  )
}

function setReadStateCache(keys: Iterable<string>, isRead: ReadStatus, advanceRevision: boolean, knownItems?: MailItem[]) {
  const wanted = new Set(keys)
  const cached = knownItems
    ? new Map(knownItems.map((item) => [mailKey(item), item]))
    : buildCachedMailIndex()
  for (const key of wanted) {
    const item = cached.get(key)
    if (item && item.is_read !== isRead) updateCachedReadStatistics(item, item.is_read, isRead)
    if (advanceRevision && (pendingReadRequests.has(key) || readOperationRevisions.has(key))) {
      readOperationRevisions.set(key, (readOperationRevisions.get(key) || 0) + 1)
    }
  }
  patchCachedMail(wanted, { is_read: isRead })
}

/**
 * Apply a bulk optimistic read state (mark-all) and return its rollback.
 *
 * The rollback is revision-guarded like the single-message path in
 * setReadOptimistic: a key is reverted only when no other writer advanced
 * its read revision after this optimistic write and every cached copy
 * still holds the optimistic value. Keys that fail either check are left
 * alone — the authoritative invalidation that follows a failed bulk call
 * reconciles them with the server instead of clobbering newer state (A149).
 */
export function applyCachedReadStateWithRollback(keys: Iterable<string>, nextRead: boolean, previousRead: boolean): (() => void) & { commit: () => void } {
  const wanted = [...new Set(keys)]
  const revisions = new Map<string, number>()
  for (const key of wanted) {
    const revision = (readOperationRevisions.get(key) || 0) + 1
    readOperationRevisions.set(key, revision)
    revisions.set(key, revision)
  }
  if (wanted.length) setReadStateCache(wanted, nextRead, false)
  let settled = false
  const rollback = (() => {
    if (settled) return
    settled = true
    for (const key of wanted) {
      if (readOperationRevisions.get(key) !== revisions.get(key)) continue
      const states = readStatesForKeys([key]).get(key) || []
      if (!states.length || states.some((state) => state !== nextRead)) continue
      setReadStateCache([key], previousRead, false)
      if (!pendingReadRequests.has(key) && readOperationRevisions.get(key) === revisions.get(key)) {
        readOperationRevisions.delete(key)
      }
    }
  }) as (() => void) & { commit: () => void }
  /** Success path: drop this write's revision entries so the map stays bounded. */
  rollback.commit = () => {
    if (settled) return
    settled = true
    for (const key of wanted) {
      if (!pendingReadRequests.has(key) && readOperationRevisions.get(key) === revisions.get(key)) {
        readOperationRevisions.delete(key)
      }
    }
  }
  return rollback
}

function invalidateMailListsNow(client: typeof queryClient = queryClient): Promise<void> {
  return client.invalidateQueries({ predicate: (query) => isMailListQueryKey(query.queryKey) })
}

function invalidateMailStatsNow(client: typeof queryClient = queryClient): Promise<void> {
  return client.invalidateQueries({
    predicate: (query) => Array.isArray(query.queryKey)
      && query.queryKey[0] === 'mail-core'
      && (query.queryKey[1] === 'stats' || query.queryKey[1] === 'folder-stats' || query.queryKey[1] === 'account-folders'),
  })
}

function hasMailRefreshInFlight(): boolean {
  if (readRefreshInFlight) return true
  return queryClient.getQueryCache().getAll().some((query) => {
    if (query.state.fetchStatus !== 'fetching') return false
    const key = query.queryKey
    return isMailListQueryKey(key)
      || (key[0] === 'mail-core' && ['stats', 'folder-stats', 'account-folders'].includes(String(key[1])))
  })
}

export function invalidateMailListQueries(client: typeof queryClient = queryClient): Promise<void> {
  if (pendingReadMutationCount > 0 || bulkReadRequested || bulkReadInFlight || readRefreshInFlight) {
    deferredListInvalidation = true
    return Promise.resolve()
  }
  return invalidateMailListsNow(client)
}

export function invalidateMailStatsQueries(client: typeof queryClient = queryClient): Promise<void> {
  if (pendingReadMutationCount > 0 || bulkReadRequested || bulkReadInFlight || readRefreshInFlight) {
    deferredStatsInvalidation = true
    return Promise.resolve()
  }
  return invalidateMailStatsNow(client)
}

async function drainDeferredReadRefresh(): Promise<void> {
  while (true) {
    if (readRefreshPromise) {
      await readRefreshPromise
      continue
    }
    if (pendingReadMutationCount > 0 || (!deferredListInvalidation && !deferredStatsInvalidation)) return

    readRefreshInFlight = true
    const refresh = (async () => {
      while (pendingReadMutationCount === 0 && (deferredListInvalidation || deferredStatsInvalidation)) {
        const invalidateLists = deferredListInvalidation
        const invalidateStats = deferredStatsInvalidation
        deferredListInvalidation = false
        deferredStatsInvalidation = false
        await Promise.all([
          invalidateLists ? Promise.resolve().then(() => invalidateMailListsNow()) : Promise.resolve(),
          invalidateStats ? Promise.resolve().then(() => invalidateMailStatsNow()) : Promise.resolve(),
        ].map((pending) => pending.catch(() => {})))
      }
    })()
    readRefreshPromise = refresh
    try {
      await refresh
    } finally {
      if (readRefreshPromise === refresh) {
        readRefreshPromise = null
        readRefreshInFlight = false
      }
    }
  }
}

async function finishReadMutation(): Promise<void> {
  pendingReadMutationCount = Math.max(0, pendingReadMutationCount - 1)
  await drainDeferredReadRefresh()
}

function acquireSingleReadMutation(): Promise<() => Promise<void>> | (() => Promise<void>) {
  if (bulkReadRequested || bulkReadInFlight) {
    return (bulkReadGate || Promise.resolve()).then(() => acquireSingleReadMutation())
  }
  activeSingleReadCount += 1
  pendingReadMutationCount += 1
  let released = false
  // Single exit for a single-read mutation (A183): the release returns the
  // active slot AND this operation's pending count together, synchronously,
  // before draining any deferred refresh. Previously setReadOptimistic
  // awaited finishReadMutation() first — whose refresh decision read a
  // pending count that still included this operation and an active count
  // the release had not yet returned — so the drain was coupled to a
  // self-decrement fallback inside finishReadMutation and any count drift
  // could park the deferred refresh (and the bulk gate) indefinitely.
  return async () => {
    if (released) return
    released = true
    activeSingleReadCount = Math.max(0, activeSingleReadCount - 1)
    if (activeSingleReadCount === 0 && singleReadDrain) {
      const resolve = resolveSingleReadDrain
      singleReadDrain = null
      resolveSingleReadDrain = null
      resolve?.()
    }
    pendingReadMutationCount = Math.max(0, pendingReadMutationCount - 1)
    await drainDeferredReadRefresh()
  }
}

export async function beginReadMutation(): Promise<() => Promise<void>> {
  while (bulkReadRequested || bulkReadInFlight) {
    await (bulkReadGate || Promise.resolve())
  }
  bulkReadRequested = true
  pendingReadMutationCount += 1
  bulkReadGate = new Promise<void>((resolve) => { resolveBulkReadGate = resolve })
  try {
    await readPreparationTail
    if (activeSingleReadCount > 0) {
      if (!singleReadDrain) {
        singleReadDrain = new Promise<void>((resolve) => { resolveSingleReadDrain = resolve })
      }
      await singleReadDrain
    }
    bulkReadInFlight = true
    bulkReadRequested = false
  } catch (error) {
    bulkReadRequested = false
    const resolve = resolveBulkReadGate
    bulkReadGate = null
    resolveBulkReadGate = null
    resolve?.()
    await finishReadMutation()
    throw error
  }

  let finished = false
  return async () => {
    if (finished) return
    finished = true
    await finishReadMutation()
    bulkReadInFlight = false
    const resolve = resolveBulkReadGate
    bulkReadGate = null
    resolveBulkReadGate = null
    resolve?.()
  }
}

async function postReadInOrder(item: MailItem, nextRead: boolean): Promise<void> {
  const key = mailKey(item)
  const previous = pendingReadRequests.get(key)
  const request = (previous ? previous.catch(() => {}) : Promise.resolve()).then(async () => {
    const result = await postMailCoreMessageRead(item.id, nextRead)
    if (result.success === false) throw new Error('服务器未接受已读状态更新')
  })
  pendingReadRequests.set(key, request)
  try {
    await request
  } finally {
    if (pendingReadRequests.get(key) === request) pendingReadRequests.delete(key)
  }
}

export async function setReadOptimistic(items: MailItem[], nextRead: boolean) {
  const validItems = new Map<string, MailItem>()
  for (const item of items) {
    if (!item || typeof item.id !== 'string' || !item.id.trim()) continue
    const key = mailKey(item)
    if (!validItems.has(key)) validItems.set(key, item)
  }
  if (!validItems.size) return

  // A no-op must not cancel an unrelated SSE or final read refresh. Active
  // read mutations still own the next authoritative refresh, so leave those
  // requests to the normal serialized path.
  if (pendingReadMutationCount === 0 && !bulkReadRequested && !bulkReadInFlight && hasMailRefreshInFlight()) {
    const cachedMailIndex = buildCachedMailIndex()
    const allAlreadyInState = [...validItems.entries()].every(([key, item]) =>
      (cachedMailIndex.get(key) || item).is_read === nextRead,
    )
    if (allAlreadyInState) return
  }

  const releaseSingleReadMutation = await acquireSingleReadMutation()
  let targets: Array<MailItem & { key: string }> = []
  const revisions = new Map<string, number>()
  const preparation = readPreparationTail.catch(() => {}).then(async () => {
    if (readRefreshInFlight) {
      // A new optimistic write may cancel the refresh currently in flight.
      // Queue both scopes so this operation starts another authoritative refresh.
      deferredListInvalidation = true
      deferredStatsInvalidation = true
    }
    await queryClient.cancelQueries({
      predicate: (query) => isMailListQueryKey(query.queryKey)
        || (query.queryKey[0] === 'mail-core' && ['stats', 'folder-stats', 'account-folders'].includes(String(query.queryKey[1]))),
    })
    const cachedMailIndex = buildCachedMailIndex()
    targets = [...validItems.entries()].map(([key, item]) => {
      const cached = cachedMailIndex.get(key)
      return cached ? { ...item, ...cached, is_read: cached.is_read, key } : { ...item, key }
    }).filter((item) => item.is_read !== nextRead)
    for (const target of targets) {
      const revision = (readOperationRevisions.get(target.key) || 0) + 1
      readOperationRevisions.set(target.key, revision)
      revisions.set(target.key, revision)
    }
    if (targets.length) setReadStateCache(targets.map((item) => item.key), nextRead, false, targets)
  })
  readPreparationTail = preparation.then(() => {}, () => {})
  try {
    await preparation
    if (!targets.length) return
    for (let start = 0; start < targets.length; start += READ_MUTATION_BATCH_SIZE) {
      const batch = targets.slice(start, start + READ_MUTATION_BATCH_SIZE)
      const results = await Promise.allSettled(batch.map((item) => postReadInOrder(item, nextRead)))
      const failed: string[] = []
      const failedItems: Array<typeof targets[number]> = []
      results.forEach((result, index) => {
        if (result.status === 'rejected') {
          failedItems.push(batch[index])
          const reason = result.reason as { message?: unknown } | undefined
          failed.push(typeof reason?.message === 'string' ? reason.message : String(result.reason))
        }
      })
      if (failed.length) {
        const rollbackItems = [...failedItems, ...targets.slice(start + batch.length)]
        let shouldInvalidate = false
        for (const item of rollbackItems) {
          const currentStates = readStatesForKeys([item.key]).get(item.key) || []
          if (readOperationRevisions.get(item.key) === revisions.get(item.key)
              && currentStates.length > 0
              && currentStates.every((state) => state === nextRead)) {
            setReadStateCache([item.key], item.is_read, true)
          } else {
            shouldInvalidate = true
          }
        }
        if (shouldInvalidate) await invalidateMailListQueries()
        await invalidateMailStatsQueries()
        throw new Error(failed.join('；'))
      }
    }
    await invalidateMailStatsQueries()
  } finally {
    // Single exit (A183): release returns the active slot and the pending
    // count together, then drains any deferred refresh.
    await releaseSingleReadMutation()
    for (const item of targets) {
      if (!pendingReadRequests.has(item.key) && readOperationRevisions.get(item.key) === revisions.get(item.key)) {
        readOperationRevisions.delete(item.key)
      }
    }
  }
}

/** Mark messages read with an optimistic cache update; reverts failures. */
export async function markReadOptimistic(items: MailItem[]) {
  return setReadOptimistic(items, true)
}

const flagOperationRevisions = new Map<string, number>()
const pendingFlagRequests = new Map<string, Promise<void>>()

/** Toggle the server-side flag with an optimistic cache update; restores the prior snapshot on failure. */
export async function flagOptimistic(item: MailItem, nextFlagged: boolean): Promise<void> {
  const key = mailKey(item)
  // R05: serialize flag intents per message and guard the rollback with
  // a per-key revision, mirroring the read path. Previously each call
  // captured its own prior snapshot and restored it unconditionally on
  // failure, so in a true→false→true sequence a late failure of the
  // first request clobbered the newest intent.
  const revision = (flagOperationRevisions.get(key) || 0) + 1
  flagOperationRevisions.set(key, revision)
  const cached = findCachedMail(key)
  const priorFlagged = cached ? cached.is_flagged : item.is_flagged
  patchCachedMail([key], { is_flagged: nextFlagged })
  const previous = pendingFlagRequests.get(key) || Promise.resolve()
  const run = previous.catch(() => {}).then(async () => {
    try {
      const result = await postMailCoreMessageFlag(item.id, nextFlagged)
      if (result.success === false) throw new Error('服务器未接受旗标更新')
    } catch (err) {
      // Restore the captured prior value only when no newer intent has
      // superseded this one — do not blind re-toggle (!nextFlagged).
      if (flagOperationRevisions.get(key) === revision) {
        patchCachedMail([key], { is_flagged: priorFlagged })
      }
      throw err
    }
  })
  pendingFlagRequests.set(key, run)
  try {
    await run
  } finally {
    if (pendingFlagRequests.get(key) === run) {
      // Chain tail: clean up and take one authoritative refresh so the
      // cache converges to the server's final state for this message.
      pendingFlagRequests.delete(key)
      if (flagOperationRevisions.get(key) === revision) flagOperationRevisions.delete(key)
      await invalidateMailListQueries().catch(() => {})
    }
  }
}
