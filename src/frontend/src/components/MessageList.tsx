import { memo, useCallback, useEffect, useMemo, useRef, useState, type Ref } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Search, RefreshCw, CheckCircle, SortAsc, Paperclip, X, Check, Flag, Mail, MailOpen, Trash2, ExternalLink, PanelLeft } from 'lucide-react'
import { api, apiRequest, type AccountSummary, type SyncRequestOut } from '../api/client'
import { syncFailureDetail, waitForSyncRequests } from '../api/sync'
import { accountScope, applyCachedReadStateWithRollback, beginReadMutation, fetchAccounts, flagOptimistic, invalidateMailListQueries, invalidateMailStatsQueries, markReadOptimistic, setReadOptimistic, queryClient, queryKeys, removeCachedMail, type MailItem } from '../api/queries'
import { fetchGlobalStats, fetchMailCoreInbox, fetchMailCoreSearch, mailCoreToMailItem, postMailCoreMarkAllRead, postMailCoreMessageTrash } from '../api/mailCore'
import type { AccountFolderStatsItemOut, AccountFolderStatsOut } from '../api/schemaTypes'
import { hasMailId, mailKey } from '../lib/mailKey'
import { MOBILE_MAX_WIDTH, useIsWide } from '../lib/viewport'
import { listTitle } from '../lib/listTitle'
import { confirmAction, errorMessage } from '../lib/actions'
import { compareMailDates } from '../lib/mailDate'
import { displayName } from '../lib/displayName'
import { formatListDate } from '../lib/listDate'
import { previewText } from '../lib/previewText'
import { useMailStore } from '../store/mailStore'
import { getDesktopPlatform } from '../lib/desktopShell'

/** Server-side search kicks in from this many characters. */
export const SEARCH_MIN_CHARS = 2
export const SEARCH_DEBOUNCE_MS = 250
const LIST_LIMIT = 100
const MESSAGE_ROW_HEIGHT = 96
const MESSAGE_ROW_GAP = 4
const MESSAGE_ROW_SLOT_HEIGHT = MESSAGE_ROW_HEIGHT + MESSAGE_ROW_GAP
const MESSAGE_LIST_OVERSCAN = 8
const FALLBACK_MESSAGE_LIST_HEIGHT = 600

/** Whether query meets CJK threshold (1+ CJK char). */
function isCjkTrigger(q: string): boolean {
  const trimmed = q.trim()
  return trimmed.length >= 1 && /[\u4e00-\u9fa5]/.test(trimmed)
}

/** Whether query meets search threshold (1+ CJK char or 2+ ascii chars). */
function isSearchTrigger(q: string): boolean {
  const trimmed = q.trim()
  if (isCjkTrigger(trimmed)) {
    return true
  }
  return trimmed.length >= SEARCH_MIN_CHARS
}

/** Max simultaneous per-account folder-stats requests in the all-accounts view (A69). */
export const FOLDER_STATS_CONCURRENCY = 8

/** Map with a bounded number of workers so a large account list cannot fan out into hundreds of simultaneous requests. */
export async function mapWithConcurrency<T, R>(items: readonly T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length) as R[]
  let nextIndex = 0
  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      results[index] = await fn(items[index])
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, () => worker()))
  return results
}

function sumKnownCounts(counts: Array<number | null>): number | null {
  if (!counts.length || counts.some((count) => count === null)) return null
  return counts.reduce<number>((sum, count) => sum + (count ?? 0), 0)
}

const MessageList = memo(function MessageList({ sidebarToggleRef }: { sidebarToggleRef?: Ref<HTMLButtonElement> }) {
  const view = useMailStore((s) => s.view)
  const selectedKey = useMailStore((s) => s.selectedKey)
  const setSelectedKey = useMailStore((s) => s.setSelectedKey)
  const setMobileView = useMailStore((s) => s.setMobileView)
  const search = useMailStore((s) => s.search)
  const setSearch = useMailStore((s) => s.setSearch)
  const listFilter = useMailStore((s) => s.listFilter)
  const setListFilter = useMailStore((s) => s.setListFilter)
  const sortNewest = useMailStore((s) => s.sortNewest)
  const toggleSort = useMailStore((s) => s.toggleSort)
  const sidebarCollapsed = useMailStore((s) => s.sidebarCollapsed)
  const mobileSidebarOpen = useMailStore((s) => s.mobileSidebarOpen)
  const toggleSidebar = useMailStore((s) => s.toggleSidebar)
  const toggleMobileSidebar = useMailStore((s) => s.toggleMobileSidebar)
  const wide = useIsWide()
  const isMacDesktop = getDesktopPlatform() === 'darwin'
  const selectedIds = useMailStore((s) => s.selectedIds)
  const toggleSelected = useMailStore((s) => s.toggleSelected)
  const selectAll = useMailStore((s) => s.selectAll)
  const clearSelected = useMailStore((s) => s.clearSelected)
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds])

  const [searchInput, setSearchInput] = useState(search)
  const [isComposing, setIsComposing] = useState(false)

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- sync local input when shared navigation search changes.
    setSearchInput(search)
  }, [search])

  useEffect(() => {
    if (searchInput === search) return
    if (isComposing) return

    const trimmed = searchInput.trim()
    if (!trimmed) {
      setSearch('')
      return
    }

    if (isCjkTrigger(trimmed)) {
      setSearch(searchInput)
      return
    }

    const timer = setTimeout(() => {
      setSearch(searchInput)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [searchInput, search, isComposing, setSearch])

  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []

  const accountId = view.type === 'account' ? view.accountId : (view.type === 'favorite' ? view.accountId : (view.type === 'folder' ? view.accountId : undefined))
  const groupId = view.type === 'group' ? view.groupId : undefined
  const favoriteCategory = view.type === 'favorite' || view.type === 'group' ? view.category : undefined
  const folderId = view.type === 'folder' ? view.folderId : undefined
  const folderRole =
    view.type === 'folder'
      ? (view.folderRole || 'other')
      : favoriteCategory === 'sent'
        ? 'sent'
        : favoriteCategory === 'drafts'
          ? 'drafts'
          : favoriteCategory === 'trash'
            ? 'trash'
            : favoriteCategory === 'junk'
              ? 'junk'
              : 'inbox'
  const effectiveFilter = favoriteCategory === 'unread' ? 'unread' : listFilter
  const term = search.trim()
  const searching = isSearchTrigger(term)
  const listScope = accountScope(accountId)

  interface InboxPageData {
    items: MailItem[]
    next_cursor: string | null
  }

  interface SearchPageData {
    items: MailItem[]
    next_offset: number | null
    total: number
  }

  const is_unread = effectiveFilter === 'unread' ? false : undefined
  const is_flagged = listFilter === 'flagged' ? true : undefined
  const sortOrder = sortNewest ? 'desc' : 'asc'

  const inboxInfiniteQuery = useInfiniteQuery<InboxPageData, Error, { pages: InboxPageData[]; pageParams: (string | null)[] }, readonly unknown[], string | null>({
    queryKey: queryKeys.inbox(listScope, effectiveFilter, folderRole, sortOrder, folderId, groupId),
    queryFn: async ({ pageParam, signal }) => {
      const page = await fetchMailCoreInbox({
        limit: LIST_LIMIT,
        accountId,
        groupId,
        folder_id: folderId,
        is_read: is_unread,
        is_flagged: is_flagged,
        folder_role: folderId ? undefined : folderRole,
        sort_order: sortOrder,
        cursor: pageParam || undefined,
        signal,
      })
      return {
        items: page.items.filter(hasMailId).map(mailCoreToMailItem),
        next_cursor: page.next_cursor ?? null,
      }
    },
    initialPageParam: null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? null,
    enabled: !searching,
    retry: false,
  })

  const searchInfiniteQuery = useInfiniteQuery<SearchPageData, Error, { pages: SearchPageData[]; pageParams: number[] }, readonly unknown[], number>({
    queryKey: queryKeys.search(term, listScope, groupId, folderId),
    queryFn: async ({ pageParam, signal }) => {
      const page = await fetchMailCoreSearch(term, { accountId, groupId, folderId, limit: LIST_LIMIT, offset: pageParam, signal })
      return {
        items: page.items.filter(hasMailId).map(mailCoreToMailItem),
        next_offset: page.next_offset ?? null,
        total: page.total,
      }
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.next_offset ?? null,
    enabled: searching,
    retry: false,
  })

  const folderStatsScope = groupId ? `group:${groupId}` : accountId ? `account:${accountId}` : 'all'
  const folderStatsQuery = useQuery({
    queryKey: ['mail-core', 'folder-stats', folderStatsScope, folderRole, folderId ?? ''],
    queryFn: async ({ signal }) => {
      if (groupId) {
        const stats = await fetchGlobalStats(signal, groupId, folderRole)
        const activeAccounts = stats.accounts.filter((item) => {
          const acc = accounts.find((a) => a.id === item.account_id)
          const isFaulty = acc && (acc.sync_enabled === false || acc.sync_status === 'failed' || acc.sync_status === 'auth_failed') && item.total_count === null
          return !isFaulty
        })
        return {
          total: activeAccounts.length ? sumKnownCounts(activeAccounts.map((item) => item.total_count)) : 0,
          unread: stats.total_unread,
        }
      }
      if (accountId) {
        const stats = await apiRequest<AccountFolderStatsOut>(`/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`, { signal }).catch(() => null)
        if (!stats) return null
        if (stats.folders.length === 0) {
          return { total: null, unread: null }
        }
        const targetFolders = folderId
          ? stats.folders.filter((f: AccountFolderStatsItemOut) => String(f.folder_id) === folderId)
          : stats.folders.filter((f: AccountFolderStatsItemOut) => f.role === folderRole)
        return {
          total: targetFolders.length ? sumKnownCounts(targetFolders.map((folder) => folder.total_count)) : 0,
          unread: targetFolders.length ? sumKnownCounts(targetFolders.map((folder) => folder.unread_count)) : 0,
        }
      }
      const enabledAccounts = accounts.filter((account) => account.sync_enabled !== false)
      const statsList = await mapWithConcurrency(enabledAccounts, FOLDER_STATS_CONCURRENCY, async (a) => {
        const res = await apiRequest<AccountFolderStatsOut>(`/api/mail/accounts/${encodeURIComponent(a.id)}/folder-stats`, { signal }).catch(() => null)
        return { account: a, stats: res }
      })
      if (statsList.some((item) => item.stats === null)) return null
      let total = 0
      let unread = 0
      let totalUnknown = false
      let unreadUnknown = false
      for (const { account: a, stats: s } of statsList) {
        if (!s) return null
        const isFaulty = (a.sync_status === 'failed' || a.sync_status === 'auth_failed') && s.folders.length === 0
        if (isFaulty) {
          continue
        }
        if (s.folders.length === 0) {
          totalUnknown = true
          unreadUnknown = true
          continue
        }
        const targetFolders = s.folders.filter((f: AccountFolderStatsItemOut) => f.role === folderRole)
        const accountTotal = targetFolders.length ? sumKnownCounts(targetFolders.map((folder) => folder.total_count)) : 0
        const accountUnread = targetFolders.length ? sumKnownCounts(targetFolders.map((folder) => folder.unread_count)) : 0
        if (accountTotal === null) totalUnknown = true
        else total += accountTotal
        if (accountUnread === null) unreadUnknown = true
        else unread += accountUnread
      }
      return { total: totalUnknown ? null : total, unread: unreadUnknown ? null : unread }
    },
    enabled: (Boolean(groupId) || Boolean(accountId) || accounts.length > 0) && !searching,
  })

  const active = searching ? searchInfiniteQuery : inboxInfiniteQuery

  const raw: MailItem[] = useMemo(() => {
    const pages = (searching ? searchInfiniteQuery.data?.pages : inboxInfiniteQuery.data?.pages) || []
    const all = pages.flatMap((p) => p.items)
    const seen = new Set<string>()
    const deduped: MailItem[] = []
    for (const item of all) {
      if (!seen.has(item.id)) {
        seen.add(item.id)
        deduped.push(item)
      }
    }
    return deduped
  }, [searching, searchInfiniteQuery.data, inboxInfiniteQuery.data])

  const hasMore = Boolean(searching ? searchInfiniteQuery.hasNextPage : inboxInfiniteQuery.hasNextPage)
  const loadingMore = Boolean(searching ? searchInfiniteQuery.isFetchingNextPage : inboxInfiniteQuery.isFetchingNextPage)
  const totalCount = searching ? (searchInfiniteQuery.data?.pages?.[0]?.total ?? null) : (folderStatsQuery.data?.total ?? null)
  const serverUnread = searching ? null : (folderStatsQuery.data?.unread ?? null)
  const totalUnknown = !searching && (
    folderStatsQuery.isError ||
    folderStatsQuery.data === null ||
    folderStatsQuery.data === undefined ||
    folderStatsQuery.data.total === null
  )
  const unreadUnknown = searching ? raw.some((m) => m.is_read === null) : (
    folderStatsQuery.isError ||
    folderStatsQuery.data === null ||
    folderStatsQuery.data === undefined ||
    folderStatsQuery.data.unread === null
  )
  const unreadCount = unreadUnknown ? null : searching ? raw.filter((m) => m.is_read === false).length : serverUnread ?? 0

  const [actionStatus, setActionStatus] = useState('')
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const messageListRef = useRef<HTMLDivElement | null>(null)
  const [messageListScrollTop, setMessageListScrollTop] = useState(0)
  const [messageListHeight, setMessageListHeight] = useState(FALLBACK_MESSAGE_LIST_HEIGHT)

  useEffect(() => {
    const element = messageListRef.current
    if (!element) return
    const updateHeight = () => {
      setMessageListHeight(element.clientHeight || FALLBACK_MESSAGE_LIST_HEIGHT)
    }
    updateHeight()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateHeight)
      return () => window.removeEventListener('resize', updateHeight)
    }
    const observer = new ResizeObserver(updateHeight)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // fetchNextPage is a bound method on the persistent query observer, so it
  // stays referentially stable across renders; depending on the whole query
  // result objects would recreate this callback (and resubscribe the
  // IntersectionObserver below) on every result identity change (A126).
  const searchFetchNextPage = searchInfiniteQuery.fetchNextPage
  const inboxFetchNextPage = inboxInfiniteQuery.fetchNextPage
  const handleLoadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return
    try {
      if (searching) {
        await searchFetchNextPage()
      } else {
        await inboxFetchNextPage()
      }
    } catch (err) {
      setActionStatus(errorMessage(err, '加载更多失败'))
    }
  }, [loadingMore, hasMore, searching, searchFetchNextPage, inboxFetchNextPage])

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasMore || loadingMore) return
    if (typeof IntersectionObserver === 'undefined') return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          void handleLoadMore()
        }
      },
      { rootMargin: '200px' }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMore, loadingMore, handleLoadMore])

  const scrollRafRef = useRef<number | null>(null)
  const pendingScrollTopRef = useRef(0)

  // Cancel a coalesced scroll update on unmount.
  useEffect(() => () => {
    if (scrollRafRef.current !== null) cancelAnimationFrame(scrollRafRef.current)
    scrollRafRef.current = null
  }, [])

  const handleScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      const { scrollTop, scrollHeight, clientHeight } = e.currentTarget
      if (scrollHeight - scrollTop - clientHeight < 150) {
        void handleLoadMore()
      }
      // F4: coalesce scroll bursts into one state update per animation
      // frame. messageListScrollTop feeds the virtualWindow memo, so an
      // unthrottled setState re-sliced the window on every scroll event.
      pendingScrollTopRef.current = scrollTop
      if (scrollRafRef.current === null) {
        scrollRafRef.current = requestAnimationFrame(() => {
          scrollRafRef.current = null
          const next = pendingScrollTopRef.current
          setMessageListScrollTop((previous) => (previous === next ? previous : next))
        })
      }
    },
    [handleLoadMore],
  )

  const visible = useMemo(() => {
    return raw
      .filter((m) => {
        if ((favoriteCategory === 'unread' || listFilter === 'unread') && m.is_read !== false) return false
        if (listFilter === 'flagged' && !m.is_flagged) return false
        return true
      })
      .sort((a, b) => compareMailDates(a.date, b.date, sortNewest))
  }, [raw, favoriteCategory, listFilter, sortNewest])

  const virtualWindow = useMemo(() => {
    const firstVisible = Math.min(visible.length, Math.floor(messageListScrollTop / MESSAGE_ROW_SLOT_HEIGHT))
    const start = Math.max(0, firstVisible - MESSAGE_LIST_OVERSCAN)
    const visibleCount = Math.max(1, Math.ceil(messageListHeight / MESSAGE_ROW_SLOT_HEIGHT))
    const end = Math.min(
      visible.length,
      firstVisible + visibleCount + MESSAGE_LIST_OVERSCAN,
    )
    return { start, end, items: visible.slice(start, end) }
  }, [visible, messageListHeight, messageListScrollTop])

  const loading = active.isLoading && !active.data
  const failure = active.error ? errorMessage(active.error, '加载邮件失败') : ''
  const isUnreadView = favoriteCategory === 'unread' || listFilter === 'unread'
  const displayTotal = isUnreadView
    ? unreadCount
    : (totalCount !== null ? Math.max(totalCount, visible.length) : visible.length)
  const countLabel = loading
    ? '正在拉取邮件…'
    : `${(isUnreadView ? unreadUnknown : totalUnknown) ? '—' : displayTotal ?? '—'} 封邮件 · ${unreadUnknown ? '—' : unreadCount} 封未读`
  const selecting = selectedIds.length > 0

  const title = listTitle(view, listFilter)

  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
    mail: MailItem
  } | null>(null)

  useEffect(() => {
    if (!contextMenu) return
    function handlePointerDown(e: MouseEvent) {
      const target = e.target as HTMLElement | null
      if (!target?.closest('.context-menu')) {
        setContextMenu(null)
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setContextMenu(null)
      }
    }
    window.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [contextMenu])

  async function handleToggleRead(m: MailItem) {
    setContextMenu(null)
    try {
      await setReadOptimistic([m], m.is_read !== true)
    } catch (err) {
      setActionStatus(errorMessage(err, '标记失败'))
    }
  }

  async function handleToggleFlag(m: MailItem) {
    setContextMenu(null)
    try {
      await flagOptimistic(m, !m.is_flagged)
    } catch (err) {
      setActionStatus(errorMessage(err, '标记失败'))
    }
  }

  async function handleTrash(m: MailItem) {
    setContextMenu(null)
    if (!confirmAction(`将「${m.subject}」移到废纸篓？`)) return
    try {
      await postMailCoreMessageTrash(m.id)
      removeCachedMail([mailKey(m)])
      if (selectedKey === mailKey(m)) setSelectedKey(null)
      await Promise.all([invalidateMailListQueries(), invalidateMailStatsQueries()])
    } catch (err) {
      setActionStatus(errorMessage(err, '删除失败'))
    }
  }

  async function markAll() {
    const unreadKeys = raw.filter((m) => m.is_read === false).map(mailKey)
    const finishReadMutation = await beginReadMutation()
    // Revision-guarded rollback (A149): reverting unconditionally would
    // clobber read states that a concurrent single-message operation or a
    // sync update legitimately changed while mark-all was in flight.
    const rollbackOptimisticRead = unreadKeys.length
      ? applyCachedReadStateWithRollback(unreadKeys, true, false)
      : null
    try {
      await postMailCoreMarkAllRead({
        accountId,
        groupId,
        folder_role: folderId ? undefined : folderRole,
        folder_id: folderId,
        is_flagged: is_flagged,
      })
      rollbackOptimisticRead?.commit()
      await Promise.all([invalidateMailListQueries(), invalidateMailStatsQueries()])
      setActionStatus('')
    } catch (err) {
      rollbackOptimisticRead?.()
      await Promise.all([invalidateMailListQueries(), invalidateMailStatsQueries()])
      setActionStatus(`标记全部已读失败：${errorMessage(err)}`)
    } finally {
      await finishReadMutation()
    }
  }

  function openMessage(m: MailItem) {
    setSelectedKey(mailKey(m))
    if (window.innerWidth <= MOBILE_MAX_WIDTH) setMobileView('detail')
    if (m.is_read === false) {
      markReadOptimistic([m]).catch((err) => setActionStatus(`标记已读失败：${errorMessage(err)}`))
    }
  }

  const [isSyncing, setIsSyncing] = useState(false)
  const syncCancelledRef = useRef(false)

  // Unmounting stops the wait (the backend sync itself keeps running).
  useEffect(() => () => {
    syncCancelledRef.current = true
  }, [])

  /**
   * Immediate sync for the accounts in the current view scope: account and
   * folder views sync their one account (all of its folders), a group view
   * syncs the group's sync-enabled accounts, and the all-inbox view syncs
   * every account. The icon spins until the sync requests truly finish —
   * success is silent, only failures surface through the status note.
   */
  async function syncCurrentScope() {
    if (isSyncing) return
    setIsSyncing(true)
    syncCancelledRef.current = false
    try {
      let submitError: unknown = null
      let initial: SyncRequestOut[]
      if (accountId) {
        initial = [await api.syncAccount(accountId)]
      } else if (groupId) {
        // The scope resolves from the account list: if it has not loaded
        // yet, wait for it instead of silently syncing an empty scope.
        // (Once loaded, an empty group legitimately syncs nothing.)
        const scopeAccounts = accountsQuery.data ?? (await queryClient.fetchQuery<AccountSummary[], Error, AccountSummary[]>({ queryKey: queryKeys.accounts, queryFn: fetchAccounts }))
        const targets = scopeAccounts.filter((account) => account.group_id === groupId && account.sync_enabled !== false)
        // allSettled, not Promise.all: one rejected submission (e.g. the
        // account vanished → 404) must not abandon the requests that were
        // created — they are waited out below, and the submission failure
        // is reported only once that wait has finished.
        const settled = await Promise.allSettled(targets.map((account) => api.syncAccount(account.id)))
        initial = []
        for (const outcome of settled) {
          if (outcome.status === 'fulfilled') initial.push(outcome.value)
          else submitError ??= outcome.reason
        }
      } else {
        initial = [await api.syncAll()]
      }
      const { reports, cancelled } = await waitForSyncRequests(initial, {
        isCancelled: () => syncCancelledRef.current,
      })
      if (cancelled) return
      const failure = syncFailureDetail(reports)
      if (failure) setActionStatus(`立即同步失败：${failure}`)
      else if (submitError) setActionStatus(`立即同步失败：${errorMessage(submitError)}`)
      await Promise.all([
        invalidateMailListQueries(),
        invalidateMailStatsQueries(),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.stats }),
      ])
    } catch (err) {
      if (!syncCancelledRef.current) setActionStatus(`立即同步失败：${errorMessage(err)}`)
    } finally {
      setIsSyncing(false)
    }
  }

  async function deleteSelected() {
    const chosen = visible.filter((m) => selectedIdSet.has(mailKey(m)))
    if (!chosen.length) return
    if (!confirmAction(`将所选 ${chosen.length} 封邮件移到废纸篓？`)) return
    const results = await Promise.allSettled(chosen.map((m) => postMailCoreMessageTrash(m.id)))
    const ok = chosen.filter((_, i) => results[i].status === 'fulfilled')
    const failed = chosen.filter((_, i) => results[i].status === 'rejected')
    removeCachedMail(ok.map(mailKey))
    clearSelected()
    if (failed.length) {
      // Keep failed items selected so the user can retry.
      selectAll(failed.map(mailKey))
      const first = results.find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined
      setActionStatus(`${failed.length} 封删除失败：${errorMessage(first?.reason)}`)
    } else {
      setActionStatus(`已删除 ${chosen.length} 封邮件`)
    }
    await Promise.all([invalidateMailListQueries(), invalidateMailStatsQueries()])
  }

  return (
    <section className="list-pane" aria-label="邮件列表">
      <div className="list-header">
        <div className="list-title-row">
          <div className="list-heading" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {!isMacDesktop && (
              <button
                ref={sidebarToggleRef}
                data-ui="ML01"
                data-testid="sidebar-toggle"
                type="button"
                className="list-primary-btn sidebar-expand-btn"
                title={wide ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (mobileSidebarOpen ? '关闭导航' : '打开导航')}
                aria-label={wide ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (mobileSidebarOpen ? '关闭导航' : '打开导航')}
                aria-expanded={wide ? !sidebarCollapsed : mobileSidebarOpen}
                onClick={wide ? toggleSidebar : toggleMobileSidebar}
              >
                <PanelLeft size={16} />
              </button>
            )}
            <div>
              <div data-ui="ML02" className="list-title" title={title}>{title}</div>
              <div className="list-count" aria-live="polite">{countLabel}</div>
            </div>
          </div>
          <div className="list-primary-actions">
            <button
              data-ui="ML03"
              className={`list-primary-btn ${isSyncing ? 'loading' : ''}`}
              title="立即同步"
              aria-label="立即同步"
              disabled={isSyncing}
              onClick={syncCurrentScope}
            >
              <RefreshCw size={16} className={isSyncing ? 'spin' : ''} />
            </button>
          </div>
        </div>
        <label className="list-search">
          <Search size={16} />
          <input
            data-ui="ML04"
            name="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onCompositionStart={() => setIsComposing(true)}
            onCompositionEnd={(e) => {
              setIsComposing(false)
              setSearchInput(e.currentTarget.value)
            }}
            placeholder="搜索邮件（主题 / 发件人 / 收件人 / 正文）"
            aria-label="搜索邮件"
          />
          {searchInput && (
            <button
              data-ui="ML05"
              className="list-primary-btn"
              title="清除搜索"
              aria-label="清除搜索"
              onClick={() => {
                setSearchInput('')
                setSearch('')
              }}
            >
              <X size={14} />
            </button>
          )}
        </label>
        {selecting ? (
          <div className="list-controls selection-bar" role="toolbar" aria-label="多选操作">
            <span className="selection-count">已选 {selectedIds.length} 封</span>
            <div className="list-control-group">
              <button data-ui="ML19" className="sort-btn" onClick={() => selectAll(visible.map((m) => mailKey(m)))} title="选择当前列表全部邮件">全选</button>
              <button data-ui="ML17" className="sort-btn danger" onClick={deleteSelected} title="移到废纸篓（删除所选）" aria-label="移到废纸篓（删除所选）">移到废纸篓</button>
              <button data-ui="ML18" className="sort-btn" onClick={clearSelected} title="取消选择">取消</button>
            </div>
          </div>
        ) : (
          <div className="list-controls">
            <div className="segmented" role="tablist" aria-label="筛选">
              <button
                data-ui="ML20"
                role="tab"
                aria-selected={listFilter === 'all'}
                className={`segment-btn ${listFilter === 'all' ? 'active' : ''}`}
                onClick={() => setListFilter('all')}
              >
                全部
              </button>
              <button
                data-ui="ML21"
                role="tab"
                aria-selected={listFilter === 'unread'}
                className={`segment-btn ${listFilter === 'unread' ? 'active' : ''}`}
                onClick={() => setListFilter('unread')}
              >
                未读
              </button>
              <button
                data-ui="ML22"
                role="tab"
                aria-selected={listFilter === 'flagged'}
                className={`segment-btn ${listFilter === 'flagged' ? 'active' : ''}`}
                onClick={() => setListFilter('flagged')}
              >
                已标记
              </button>
            </div>
            <div className="list-control-group">
              <button data-ui="ML07" className="mark-all-btn" onClick={markAll} disabled={unreadCount === 0} title="将当前列表中的邮件全部标为已读" aria-label="全部标为已读">
                <CheckCircle size={13} />
                <span className="mark-label">全部已读</span>
              </button>
              <button className="sort-btn" onClick={() => selectAll(visible.map((m) => mailKey(m)))} title="选择当前列表全部邮件" disabled={!visible.length}>
                全选
              </button>
              <button data-ui="ML06" className="sort-btn" onClick={toggleSort} title="切换邮件排序" aria-label={sortNewest ? '排序：最新优先' : '排序：最早优先'}>
                <SortAsc size={14} />
                <span>{sortNewest ? '最新' : '最早'}</span>
              </button>
            </div>
          </div>
        )}
      </div>
      <div ref={messageListRef} className={`message-list windowed ${selecting ? 'selecting' : ''}`} onScroll={handleScroll}>
        {actionStatus && actionStatus.includes('失败') && <div role="status" className="list-note error">{actionStatus}</div>}
        {failure && <div role="alert" className="list-note error">{failure}</div>}
        {!loading && visible.length === 0 && (
          <div data-ui="ML13" style={{ padding: 45, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
            {accounts.length === 0 ? '还没有账户。在设置中添加账户后，这里会显示邮件。' : searching ? '没有匹配的邮件' : '没有邮件'}
          </div>
        )}
        {visible.length > 0 && virtualWindow.start > 0 && (
          <div aria-hidden="true" className="message-list-spacer" style={{ height: virtualWindow.start * MESSAGE_ROW_SLOT_HEIGHT }} />
        )}
        {virtualWindow.items.map((m) => {
          const key = mailKey(m)
          const checked = selectedIdSet.has(key)
          return (
            <div key={key} className="message-row-slot" style={{ height: MESSAGE_ROW_SLOT_HEIGHT }}>
              <article
                data-ui="ML08"
                tabIndex={0}
                aria-label={`邮件：${m.subject || '（无主题）'}，来自 ${displayName(m.from)}`}
                className={`message-row apple-card ${selectedKey === key ? 'selected' : ''} ${m.is_read === false ? 'unread' : ''} ${checked ? 'checked' : ''}`}
                style={{ height: MESSAGE_ROW_HEIGHT, width: "100%", flex: "none" }}
                onClick={() => openMessage(m)}
                onContextMenu={(e) => {
                  e.preventDefault()
                  const menuWidth = 180
                  const menuHeight = 260
                  const x = Math.min(e.clientX, (window.innerWidth || 800) - menuWidth - 8)
                  const y = Math.min(e.clientY, (window.innerHeight || 600) - menuHeight - 8)
                  setContextMenu({ x, y, mail: m })
                  setSelectedKey(mailKey(m))
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    openMessage(m)
                  }
                }}
              >
                <button
                  className="message-check"
                  role="checkbox"
                  aria-checked={checked}
                  aria-label={`选择邮件：${m.subject}`}
                  onClick={(e) => { e.stopPropagation(); toggleSelected(key) }}
                  onKeyDown={(e) => e.stopPropagation()}
                  title="选择邮件"
                >
                  {checked && <Check size={12} />}
                </button>
                <div className="message-content">
                  <div className="message-top">
                    <span data-ui="ML09" className="sender">
                      {m.is_read === false && <span className="unread-dot" aria-label="未读" />}
                      {displayName(m.from)}
                    </span>
                    <div className="message-meta">
                      {m.is_flagged && <Flag size={12} aria-label="已标记" />}
                      {m.has_attachments && <Paperclip size={12} aria-label="有附件" />}
                      <time data-ui="ML11" className="message-date">{formatListDate(m.date)}</time>
                    </div>
                  </div>
                  <div data-ui="ML10" className="subject">{m.subject}</div>
                  <div data-ui="ML12" className="preview">{previewText(m.body_preview)}</div>
                </div>
              </article>
            </div>
          )
        })}
        {visible.length > 0 && virtualWindow.end < visible.length && (
          <div aria-hidden="true" className="message-list-spacer" style={{ height: (visible.length - virtualWindow.end) * MESSAGE_ROW_SLOT_HEIGHT }} />
        )}
        {!loading && (
          <div className="list-footer" style={{ padding: '16px', textAlign: 'center' }}>
            {hasMore && (
              <div
                ref={sentinelRef}
                className="list-sentinel"
                style={{ height: 1, width: '100%', pointerEvents: 'none' }}
              />
            )}
            {loadingMore ? (
              <div
                className="list-loading-more"
                style={{
                  fontSize: 12,
                  color: 'var(--muted)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  justifyContent: 'center',
                }}
              >
                <RefreshCw size={13} className="spin" />
                <span>正在加载更多邮件…</span>
              </div>
            ) : !hasMore && visible.length > 0 ? (
              <span className="list-all-loaded" style={{ fontSize: 11, color: 'var(--muted)' }}>
                已加载全部邮件
              </span>
            ) : null}
          </div>
        )}
      </div>
      {contextMenu && (
        <div
          className="context-menu"
          role="menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            className="context-menu-item"
            role="menuitem"
            onClick={() => {
              const m = contextMenu.mail
              setContextMenu(null)
              openMessage(m)
            }}
          >
            <ExternalLink size={14} />
            <span>打开</span>
          </button>

          <div className="context-menu-separator" />

          <button
            type="button"
            className="context-menu-item"
            role="menuitem"
            onClick={() => handleToggleRead(contextMenu.mail)}
          >
            {contextMenu.mail.is_read ? <Mail size={14} /> : <MailOpen size={14} />}
            <span>{contextMenu.mail.is_read ? '标为未读' : '标为已读'}</span>
          </button>

          <button
            type="button"
            className="context-menu-item"
            role="menuitem"
            onClick={() => handleToggleFlag(contextMenu.mail)}
          >
            <Flag size={14} />
            <span>{contextMenu.mail.is_flagged ? '取消旗标' : '标记旗标'}</span>
          </button>

          <div className="context-menu-separator" />

          <button
            type="button"
            className="context-menu-item danger"
            role="menuitem"
            onClick={() => handleTrash(contextMenu.mail)}
          >
            <Trash2 size={14} />
            <span>移到废纸篓</span>
          </button>
        </div>
      )}
    </section>
  )
})

export default MessageList
