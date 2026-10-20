import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Search, RefreshCw, CheckCircle, SortAsc, Paperclip, Menu, X, Check, Flag } from 'lucide-react'
import { accountScope, fetchAccounts, markReadOptimistic, queryClient, queryKeys, removeCachedMail, type MailItem } from '../api/queries'
import { fetchMailCoreInbox, fetchMailCoreSearch, mailCoreToMailItem, postMailCoreMessageTrash } from '../api/mailCore'
import { hasMailId, mailKey } from '../lib/mailKey'
import { listTitle } from '../lib/listTitle'
import { confirmAction, errorMessage } from '../lib/actions'
import { compareMailDates } from '../lib/mailDate'
import { displayName } from '../lib/displayName'
import { formatListDate } from '../lib/listDate'
import { previewText } from '../lib/previewText'
import { useMailStore } from '../store/mailStore'

/** Server-side search kicks in from this many characters. */
export const SEARCH_MIN_CHARS = 2
const LIST_LIMIT = 100

export default function MessageList() {
  const {
    view,
    selectedKey,
    setSelectedKey,
    setMobileView,
    search,
    setSearch,
    listFilter,
    setListFilter,
    sortNewest,
    toggleSort,
    toggleMobileSidebar,
    selectedIds,
    toggleSelected,
    selectAll,
    clearSelected,
  } = useMailStore()

  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []

  const accountId = view.type === 'account' ? view.accountId : undefined
  const term = search.trim()
  const searching = term.length >= SEARCH_MIN_CHARS
  const listScope = accountScope(accountId)
  const inboxQuery = useQuery<MailItem[]>({
    queryKey: queryKeys.inbox(listScope),
    queryFn: ({ signal }) =>
      fetchMailCoreInbox({ limit: LIST_LIMIT, accountId, signal }).then((page) =>
        page.items.filter(hasMailId).map(mailCoreToMailItem),
      ),
    enabled: !searching,
    retry: false,
    placeholderData: keepPreviousData,
  })
  const searchQuery = useQuery<MailItem[]>({
    queryKey: queryKeys.search(term, listScope),
    queryFn: ({ signal }) =>
      fetchMailCoreSearch(term, { accountId, limit: LIST_LIMIT, signal }).then((page) =>
        page.items.filter(hasMailId).map(mailCoreToMailItem),
      ),
    enabled: searching,
    retry: false,
    placeholderData: keepPreviousData,
  })
  const active = searching ? searchQuery : inboxQuery
  const raw: MailItem[] = active.data || []

  const visible = raw
    .filter((m) => {
      if (listFilter === 'unread' && m.is_read) return false
      if (listFilter === 'flagged' && !m.is_flagged) return false
      return true
    })
    .sort((a, b) => compareMailDates(a.date, b.date, sortNewest))

  const [actionStatus, setActionStatus] = useState('')
  const unreadCount = raw.filter((m) => !m.is_read).length
  const loading = active.isLoading && !active.data
  const failure = active.error ? errorMessage(active.error, '加载邮件失败') : ''
  const countLabel = loading
    ? '正在拉取邮件…'
    : `${visible.length} 封邮件 · ${unreadCount} 封未读`
  const selecting = selectedIds.length > 0

  const title = listTitle(view, listFilter)

  async function markAll() {
    try {
      await markReadOptimistic(visible)
      setActionStatus('')
    } catch (err) {
      setActionStatus(`部分账户标记失败：${errorMessage(err)}`)
    }
  }

  function openMessage(m: MailItem) {
    setSelectedKey(mailKey(m))
    if (window.innerWidth <= 760) setMobileView('detail')
    if (!m.is_read) {
      markReadOptimistic([m]).catch((err) => setActionStatus(`标记已读失败：${errorMessage(err)}`))
    }
  }

  function refreshView() {
    void queryClient.invalidateQueries({ queryKey: ['mail-core'], refetchType: 'active' })
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
          <div className="list-heading">
            <div className="list-title" title={title}>{title}</div>
            <div className="list-count" aria-live="polite">{countLabel}</div>
          </div>
          <div className="list-primary-actions">
            <button className="list-primary-btn mobile-only" title="账户导航" aria-label="账户导航" onClick={toggleMobileSidebar}>
              <Menu size={16} />
            </button>
            <button className="list-primary-btn" title="刷新" aria-label="刷新" onClick={refreshView}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        <label className="list-search">
          <Search size={16} />
          <input name="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索邮件（主题 / 发件人 / 正文）" aria-label="搜索邮件" />
          {search && <button className="list-primary-btn" title="清除搜索" aria-label="清除搜索" onClick={() => setSearch('')}><X size={14} /></button>}
        </label>
        {selecting ? (
          <div className="list-controls selection-bar" role="toolbar" aria-label="多选操作">
            <span className="selection-count">已选 {selectedIds.length} 封</span>
            <div className="list-control-group">
              <button className="sort-btn" onClick={() => selectAll(visible.map((m) => mailKey(m)))} title="选择当前列表全部邮件">全选</button>
              <button className="sort-btn danger" onClick={deleteSelected} title="删除所选邮件">删除所选</button>
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
              <button className="mark-all-btn" onClick={markAll} disabled={unreadCount === 0} title="将当前列表中的邮件全部标为已读" aria-label="全部标为已读">
                <CheckCircle size={13} />
                <span className="mark-label">全部已读</span>
              </button>
              <button className="sort-btn" onClick={() => selectAll(visible.map((m) => mailKey(m)))} title="选择当前列表全部邮件" disabled={!visible.length}>
                全选
              </button>
              <button className="sort-btn" onClick={toggleSort} title="切换邮件排序" aria-label={sortNewest ? '排序：最新优先' : '排序：最早优先'}>
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
          <div style={{ padding: 45, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
            {accounts.length === 0 ? '还没有账户。在设置中添加账户后，这里会显示邮件。' : searching ? '没有匹配的邮件' : '没有邮件'}
          </div>
        )}
        {visible.map((m) => {
          const key = mailKey(m)
          const checked = selectedIds.includes(key)
          return (
            <article
              key={key}
              role="button"
              tabIndex={0}
              aria-selected={selectedKey === key}
              aria-label={`邮件：${m.subject || '（无主题）'}，来自 ${displayName(m.from)}`}
              className={`message-row apple-card ${selectedKey === key ? 'selected' : ''} ${!m.is_read ? 'unread' : ''} ${checked ? 'checked' : ''}`}
              onClick={() => openMessage(m)}
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
                title="选择邮件"
              >
                {checked && <Check size={12} />}
              </button>
              <div className="message-content">
                <div className="message-top">
                  <span className="sender">
                    {!m.is_read && <span className="unread-dot" aria-label="未读" />}
                    {displayName(m.from)}
                  </span>
                  <div className="message-meta">
                    {m.is_flagged && <Flag size={12} aria-label="已标记" />}
                    {m.has_attachments && <Paperclip size={12} aria-label="有附件" />}
                    <time className="message-date">{formatListDate(m.date)}</time>
                  </div>
                </div>
                <div className="subject">{m.subject}</div>
                <div className="preview">{previewText(m.body_preview)}</div>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
