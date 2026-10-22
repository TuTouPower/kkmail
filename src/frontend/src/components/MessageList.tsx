import { memo, useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Search, RefreshCw, CheckCircle, SortAsc, Paperclip, X, Check, Flag, Mail, MailOpen, Trash2, ExternalLink, PanelLeft } from 'lucide-react'
import { api, apiRequest } from '../api/client'
import { accountScope, fetchAccounts, flagOptimistic, markReadOptimistic, setCachedReadState, setReadOptimistic, queryClient, queryKeys, removeCachedMail, type MailItem } from '../api/queries'
import { fetchMailCoreInbox, fetchMailCoreSearch, mailCoreToMailItem, postMailCoreMarkAllRead, postMailCoreMessageTrash } from '../api/mailCore'
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

/** Server-side search kicks in from this many characters. */
export const SEARCH_MIN_CHARS = 2
export const SEARCH_DEBOUNCE_MS = 250
const LIST_LIMIT = 100

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

const MessageList = memo(function MessageList() {
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
  const toggleSidebar = useMailStore((s) => s.toggleSidebar)
  const toggleMobileSidebar = useMailStore((s) => s.toggleMobileSidebar)
  const wide = useIsWide()
  const selectedIds = useMailStore((s) => s.selectedIds)
  const toggleSelected = useMailStore((s) => s.toggleSelected)
  const selectAll = useMailStore((s) => s.selectAll)
  const clearSelected = useMailStore((s) => s.clearSelected)

  const [searchInput, setSearchInput] = useState(search)
  const [isComposing, setIsComposing] = useState(false)

  useEffect(() => {
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
  const favoriteCategory = view.type === 'favorite' ? view.category : undefined
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
    queryKey: queryKeys.inbox(listScope, effectiveFilter, folderRole, sortOrder, folderId),
    queryFn: async ({ pageParam, signal }) => {
      const page = await fetchMailCoreInbox({
        limit: LIST_LIMIT,
        accountId,
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
    placeholderData: keepPreviousData,
  })

  const searchInfiniteQuery = useInfiniteQuery<SearchPageData, Error, { pages: SearchPageData[]; pageParams: number[] }, readonly unknown[], number>({
    queryKey: queryKeys.search(term, listScope),
    queryFn: async ({ pageParam, signal }) => {
      const page = await fetchMailCoreSearch(term, { accountId, limit: LIST_LIMIT, offset: pageParam, signal })
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
    placeholderData: keepPreviousData,
  })

  const folderStatsQuery = useQuery({
    queryKey: ['mail-core', 'folder-stats', accountId ?? 'all', folderRole, folderId ?? ''],
    queryFn: async () => {
      if (accountId) {
        const stats = await apiRequest<AccountFolderStatsOut>(`/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`).catch(() => null)
        if (!stats) return null
        const targetFolder = folderId
          ? stats.folders.find((f: AccountFolderStatsItemOut) => String(f.folder_id) === folderId)
          : stats.folders.find((f: AccountFolderStatsItemOut) => f.role === folderRole)
        return {
          total: targetFolder ? targetFolder.total_count : (folderId ? 0 : stats.folders.reduce((sum: number, f: AccountFolderStatsItemOut) => sum + f.total_count, 0)),
          unread: targetFolder ? targetFolder.unread_count : (folderId ? 0 : stats.folders.reduce((sum: number, f: AccountFolderStatsItemOut) => sum + (f.unread_count || 0), 0)),
        }
      }
      const statsList = await Promise.all(
        accounts.map((a) =>
          apiRequest<AccountFolderStatsOut>(`/api/mail/accounts/${encodeURIComponent(a.id)}/folder-stats`).catch(() => null),
        ),
      )
      let total = 0
      let unread = 0
      let hasAny = false
      for (const s of statsList) {
        if (!s) continue
        hasAny = true
        const targetFolder = s.folders.find((f: AccountFolderStatsItemOut) => f.role === folderRole)
        total += targetFolder ? targetFolder.total_count : s.folders.reduce((sum: number, f: AccountFolderStatsItemOut) => sum + f.total_count, 0)
        unread += targetFolder ? targetFolder.unread_count : s.folders.reduce((sum: number, f: AccountFolderStatsItemOut) => sum + (f.unread_count || 0), 0)
      }
      return hasAny ? { total, unread } : null
    },
    enabled: accounts.length > 0 && !searching,
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
  const unreadCount = Math.max(serverUnread ?? 0, raw.filter((m) => !m.is_read).length)

  async function handleLoadMore() {
    if (loadingMore || !hasMore) return
    try {
      if (searching) {
        await searchInfiniteQuery.fetchNextPage()
      } else {
        await inboxInfiniteQuery.fetchNextPage()
      }
    } catch (err) {
      setActionStatus(errorMessage(err, '加载更多失败'))
    }
  }

  const visible = useMemo(() => {
    return raw
      .filter((m) => {
        if ((favoriteCategory === 'unread' || listFilter === 'unread') && m.is_read) return false
        if (listFilter === 'flagged' && !m.is_flagged) return false
        return true
      })
      .sort((a, b) => compareMailDates(a.date, b.date, sortNewest))
  }, [raw, favoriteCategory, listFilter, sortNewest])

  const [actionStatus, setActionStatus] = useState('')
  const loading = active.isLoading && !active.data
  const failure = active.error ? errorMessage(active.error, '加载邮件失败') : ''
  const countLabel = loading
    ? '正在拉取邮件…'
    : `${visible.length} 封邮件 · ${unreadCount} 封未读`
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
      await setReadOptimistic([m], !m.is_read)
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
      await queryClient.invalidateQueries({ queryKey: ['mail-core'] })
    } catch (err) {
      setActionStatus(errorMessage(err, '删除失败'))
    }
  }

  async function markAll() {
    const unreadKeys = raw.filter((m) => !m.is_read).map(mailKey)
    if (unreadKeys.length) {
      setCachedReadState(unreadKeys, true)
    }
    try {
      await postMailCoreMarkAllRead({
        accountId,
        folder_role: folderId ? undefined : folderRole,
        folder_id: folderId,
        is_flagged: is_flagged,
      })
      await queryClient.invalidateQueries({ queryKey: ['mail-core'] })
      setActionStatus('')
    } catch (err) {
      if (unreadKeys.length) {
        setCachedReadState(unreadKeys, false)
      }
      setActionStatus(`标记全部已读失败：${errorMessage(err)}`)
    }
  }

  function openMessage(m: MailItem) {
    setSelectedKey(mailKey(m))
    if (window.innerWidth <= MOBILE_MAX_WIDTH) setMobileView('detail')
    if (!m.is_read) {
      markReadOptimistic([m]).catch((err) => setActionStatus(`标记已读失败：${errorMessage(err)}`))
    }
  }

  const [isSyncing, setIsSyncing] = useState(false)

  async function refreshView() {
    setIsSyncing(true)
    setActionStatus('正在同步邮件…')
    try {
      const activeAccountId = 'accountId' in view && typeof view.accountId === 'string' ? view.accountId : undefined
      if (activeAccountId) {
        await api.syncAccount(activeAccountId)
        setActionStatus('已触发账户同步')
      } else {
        await api.syncAll()
        setActionStatus('已触发全量同步')
      }
    } catch (err) {
      setActionStatus(`同步触发失败：${errorMessage(err)}`)
    } finally {
      setIsSyncing(false)
      void queryClient.invalidateQueries({ queryKey: ['mail-core'], refetchType: 'active' })
      void queryClient.invalidateQueries({ queryKey: queryKeys.accounts })
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats })
    }
  }

  async function deleteSelected() {
    const chosen = visible.filter((m) => selectedIds.includes(mailKey(m)))
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
    await queryClient.invalidateQueries({ queryKey: ['mail-core'] })
  }

  return (
    <section className="list-pane" aria-label="邮件列表">
      <div className="list-header">
        <div className="list-title-row">
          <div className="list-heading" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {(!wide || sidebarCollapsed) && (
              <button
                data-ui="ML01"
                type="button"
                className="list-primary-btn sidebar-expand-btn"
                title={wide ? '展开侧边栏' : '打开导航'}
                aria-label={wide ? '展开侧边栏' : '打开导航'}
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
              title={isSyncing ? '正在同步…' : '刷新并同步'}
              aria-label={isSyncing ? '正在同步…' : '刷新并同步'}
              disabled={isSyncing}
              onClick={refreshView}
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
            placeholder="搜索邮件（主题 / 发件人 / 正文）"
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
              <button className="sort-btn" onClick={() => selectAll(visible.map((m) => mailKey(m)))} title="选择当前列表全部邮件">全选</button>
              <button className="sort-btn danger" onClick={deleteSelected} title="移到废纸篓（删除所选）" aria-label="移到废纸篓（删除所选）">移到废纸篓</button>
              <button className="sort-btn" onClick={clearSelected} title="取消选择">取消</button>
            </div>
          </div>
        ) : (
          <div className="list-controls">
            <div className="segmented" role="tablist" aria-label="筛选">
              {(['all', 'unread', 'flagged'] as const).map((f) => (
                <button key={f} role="tab" aria-selected={listFilter === f} className={`segment-btn ${listFilter === f ? 'active' : ''}`} onClick={() => setListFilter(f)}>
                  {f === 'all' ? '全部' : f === 'unread' ? '未读' : '已标记'}
                </button>
              ))}
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
      <div className={`message-list ${selecting ? 'selecting' : ''}`}>
        {actionStatus && <div role="status" className={`list-note ${actionStatus.includes('失败') ? 'error' : ''}`}>{actionStatus}</div>}
        {failure && <div role="alert" className="list-note error">{failure}</div>}
        {!loading && visible.length === 0 && (
          <div data-ui="ML13" style={{ padding: 45, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
            {accounts.length === 0 ? '还没有账户。在设置中添加账户后，这里会显示邮件。' : searching ? '没有匹配的邮件' : '没有邮件'}
          </div>
        )}
        {visible.map((m) => {
          const key = mailKey(m)
          const checked = selectedIds.includes(key)
          return (
            <article
              data-ui="ML08"
              key={key}
              tabIndex={0}
              aria-selected={selectedKey === key}
              aria-label={`邮件：${m.subject || '（无主题）'}，来自 ${displayName(m.from)}`}
              className={`message-row apple-card ${selectedKey === key ? 'selected' : ''} ${!m.is_read ? 'unread' : ''} ${checked ? 'checked' : ''}`}
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
                    {!m.is_read && <span className="unread-dot" aria-label="未读" />}
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
          )
        })}
        {!loading && (visible.length > 0 || hasMore) && (
          <div className="list-pagination" style={{ padding: '16px', textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
              {totalCount !== null
                ? `已加载 ${visible.length} 封 / 共 ${Math.max(totalCount, visible.length)} 封`
                : `已加载 ${visible.length} 封`}
            </div>
            {hasMore ? (
              <button
                data-ui="ML14"
                type="button"
                className="load-more-btn"
                onClick={handleLoadMore}
                disabled={loadingMore}
                style={{
                  padding: '6px 16px',
                  fontSize: 13,
                  borderRadius: 6,
                  border: '1px solid var(--line)',
                  background: 'var(--surface-2)',
                  color: 'var(--text)',
                  cursor: loadingMore ? 'not-allowed' : 'pointer',
                }}
              >
                {loadingMore ? '正在加载…' : '加载更多'}
              </button>
            ) : (
              visible.length > 0 && (
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>已加载全部邮件</span>
              )
            )}
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
