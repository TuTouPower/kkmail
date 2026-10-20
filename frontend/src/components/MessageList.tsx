import { useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Search, PenSquare, RefreshCw, CheckCircle, SortAsc, Paperclip, Menu, X, Check } from 'lucide-react'
import { ALL_INBOX_ACCOUNT_LIMIT, fetchAccounts, fetchEmails, markReadOptimistic, queryClient, queryKeys, type MailItem } from '../api/queries'
import { mailKey } from '../lib/mailKey'
import { listTitle } from '../lib/listTitle'
import { confirmAction, ensureSuccess, errorMessage } from '../lib/actions'
import { parseMailDate, compareMailDates } from '../lib/mailDate'
import { api } from '../api/client'
import { useMailStore } from '../store/mailStore'

function formatWhen(value?: string) {
  if (!value) return ''
  const d = new Date(parseMailDate(value))
  if (Number.isNaN(d.getTime())) return value.slice(5, 16)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

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
    flaggedIds,
    sortNewest,
    toggleSort,
    openCompose,
    toggleMobileSidebar,
    selectedIds,
    toggleSelected,
    selectAll,
    clearSelected,
  } = useMailStore()

  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const accounts = accountsQuery.data || []

  const singleEmail = view.type === 'accountFolder' ? view.email : ''
  const singleFolder = view.type === 'accountFolder' ? view.folder : 'inbox'
  const singleQuery = useQuery({
    queryKey: queryKeys.emails(singleEmail, singleFolder),
    queryFn: ({ signal }) => fetchEmails(singleEmail, singleFolder, view.type === 'accountFolder' ? view.accountId : undefined, signal),
    enabled: view.type === 'accountFolder' && !!singleEmail,
    retry: false,
  })

  // One independent query per account: each resolves (or fails/times out) on
  // its own, rows render as soon as any account answers, and leaving the view
  // aborts in-flight requests via the query signal.
  const allAccounts = view.type === 'allInbox' ? accounts.slice(0, ALL_INBOX_ACCOUNT_LIMIT) : []
  const allQueries = useQueries({
    queries: allAccounts.map((a) => ({
      queryKey: queryKeys.emails(a.email, 'inbox'),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchEmails(a.email, 'inbox', a.id, signal),
      enabled: view.type === 'allInbox',
      retry: false,
    })),
  })

  const raw: MailItem[] = view.type === 'accountFolder'
    ? (singleQuery.data || [])
    : allQueries.flatMap((q) => q.data || [])

  const searched = search
    ? raw.filter((m) => [m.from, m.subject, m.body_preview, m.accountEmail].join(' ').toLowerCase().includes(search.toLowerCase()))
    : raw
  const visible = searched
    .filter((m) => {
      if (listFilter === 'unread' && m.is_read) return false
      if (listFilter === 'flagged' && !flaggedIds.includes(mailKey(m))) return false
      return true
    })
    .sort((a, b) => compareMailDates(a.date, b.date, sortNewest))

  const [actionStatus, setActionStatus] = useState('')
  const truncatedAccounts = view.type === 'allInbox' ? Math.max(0, accounts.length - ALL_INBOX_ACCOUNT_LIMIT) : 0
  // Count unread over the whole (searched) list, independent of the tab filter,
  // so it matches the sidebar badge, which sums the same cached lists.
  const unreadCount = searched.filter((m) => !m.is_read).length
  const pendingAccounts = view.type === 'allInbox' ? allQueries.filter((q) => q.isLoading).length : 0
  const loading = view.type === 'accountFolder' ? singleQuery.isLoading : accountsQuery.isLoading || (pendingAccounts > 0 && raw.length === 0)
  const failures: string[] = view.type === 'accountFolder'
    ? (singleQuery.error ? [errorMessage(singleQuery.error, String(singleQuery.error))] : [])
    : allQueries.flatMap((q, i) => (q.error ? [`${allAccounts[i]?.email}：${errorMessage(q.error, String(q.error))}`] : []))
  const countLabel = loading
    ? '正在拉取邮件…'
    : `${visible.length} 封邮件 · ${unreadCount} 封未读${pendingAccounts ? ` · ${pendingAccounts} 个账户加载中` : ''}`
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
    if (view.type === 'accountFolder') {
      queryClient.invalidateQueries({ queryKey: queryKeys.emails(view.email, view.folder) })
    } else {
      queryClient.invalidateQueries({ queryKey: ['emails'] })
    }
  }

  async function deleteSelected() {
    const chosen = visible.filter((m) => selectedIds.includes(mailKey(m)))
    if (!chosen.length) return
    const inTrash = chosen.some((m) => (m.folder || singleFolder) === 'deleteditems')
    const warning = inTrash ? '废纸篓中的邮件将被永久删除，无法恢复。' : '邮件将移到废纸篓（IMAP 账户可能直接永久删除）。'
    if (!confirmAction(`删除所选 ${chosen.length} 封邮件？${warning}`)) return
    const groups = new Map<string, MailItem[]>()
    chosen.forEach((m) => {
      const list = groups.get(m.accountEmail) || []
      list.push(m)
      groups.set(m.accountEmail, list)
    })
    const entries = [...groups.entries()]
    const results = await Promise.allSettled(entries.map(async ([email, items]) => ensureSuccess(await api.deleteEmails({
      email,
      folder: items[0]?.folder || singleFolder,
      items: items.map((m) => ({ id: m.id, folder: m.folder || singleFolder, id_mode: m.id_mode || '' })),
    }), `${email} 删除失败`)))
    const failedEmails = new Set<string>()
    const messages: string[] = []
    results.forEach((r, i) => {
      if (r.status === 'rejected') {
        failedEmails.add(entries[i][0])
        messages.push(errorMessage(r.reason))
      }
    })
    // Keep failed items selected so the user can retry.
    clearSelected()
    if (failedEmails.size) {
      selectAll(chosen.filter((m) => failedEmails.has(m.accountEmail)).map((m) => mailKey(m)))
      setActionStatus(`删除失败：${messages.join('；')}`)
    } else {
      setActionStatus(`已删除 ${chosen.length} 封邮件`)
    }
    await queryClient.invalidateQueries({ queryKey: ['emails'] })
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
            <button className="list-primary-btn" title="写邮件" aria-label="写邮件" onClick={() => openCompose('new')}>
              <PenSquare size={16} />
            </button>
            <button className="list-primary-btn" title="刷新" aria-label="刷新" onClick={refreshView}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        <label className="list-search">
          <Search size={16} />
          <input name="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索当前列表" aria-label="搜索当前列表" />
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
        {truncatedAccounts > 0 && (
          <div role="note" className="list-note">
            所有收件箱仅汇总前 {ALL_INBOX_ACCOUNT_LIMIT} 个账户，另有 {truncatedAccounts} 个账户未包含；请在左侧选择单个账户查看。
          </div>
        )}
        {actionStatus && <div role="status" className={`list-note ${actionStatus.includes('失败') ? 'error' : ''}`}>{actionStatus}</div>}
        {failures.map((f) => (
          <div key={f} role="alert" className="list-note error">
            {view.type === 'allInbox' ? `账户加载失败 · ${f}` : f}
          </div>
        ))}
        {!loading && visible.length === 0 && !pendingAccounts && (
          <div style={{ padding: 45, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
            {accounts.length === 0 ? '还没有账户。在设置或旧版界面中添加账户后，这里会显示真实邮件。' : '没有找到邮件'}
          </div>
        )}
        {visible.map((m) => {
          const key = mailKey(m)
          const checked = selectedIds.includes(key)
          return (
            <article
              key={key}
              className={`message-row ${selectedKey === key ? 'selected' : ''} ${!m.is_read ? 'unread' : ''} ${checked ? 'checked' : ''}`}
              onClick={() => openMessage(m)}
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
              <div className="avatar" style={{ background: '#6d8fd1' }}>{(m.from || '?').slice(0, 1).toUpperCase()}</div>
              <div className="message-content">
                <div className="message-top">
                  <span className="sender">
                    {!m.is_read && <span className="unread-dot" aria-label="未读" style={{ display: 'inline-block', marginRight: 5, verticalAlign: 'middle' }} />}
                    {m.from}
                  </span>
                  <time className="message-date">{formatWhen(m.date)}</time>
                </div>
                <div className="subject">{m.subject}</div>
                <div className="preview">{m.body_preview}</div>
                <div className="message-bottom">
                  <span className="mail-account-tag">{m.accountEmail}</span>
                  {m.has_attachments && <Paperclip size={12} aria-label="有附件" />}
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
