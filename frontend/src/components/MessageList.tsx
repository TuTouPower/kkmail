import { useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Search, PenSquare, RefreshCw, CheckCircle, SortAsc, MoreHorizontal, Paperclip, Menu, X } from 'lucide-react'
import { ALL_INBOX_ACCOUNT_LIMIT, fetchAccounts, fetchEmails, markEmailsRead, queryClient, queryKeys, type MailItem } from '../api/queries'
import { confirmAction, ensureSuccess, errorMessage } from '../lib/actions'
import { api } from '../api/client'
import { useMailStore } from '../store/mailStore'

function formatWhen(value?: string) {
  if (!value) return ''
  const d = new Date(value)
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
    queryFn: () => fetchEmails(singleEmail, singleFolder, view.type === 'accountFolder' ? view.accountId : undefined),
    enabled: view.type === 'accountFolder' && !!singleEmail,
  })

  const allQueries = useQueries({
    queries: (view.type === 'allInbox' ? accounts.slice(0, ALL_INBOX_ACCOUNT_LIMIT) : []).map((a) => ({
      queryKey: queryKeys.emails(a.email, 'inbox'),
      queryFn: () => fetchEmails(a.email, 'inbox', a.id),
      enabled: view.type === 'allInbox',
    })),
  })

  const raw: MailItem[] = view.type === 'accountFolder'
    ? (singleQuery.data || [])
    : allQueries.flatMap((q) => q.data || [])

  const visible = raw
    .filter((m) => {
      if (listFilter === 'unread' && m.is_read) return false
      if (listFilter === 'flagged' && !flaggedIds.includes(`${m.accountEmail}:${m.id}`)) return false
      if (search) {
        const hay = [m.from, m.subject, m.body_preview, m.accountEmail].join(' ').toLowerCase()
        if (!hay.includes(search.toLowerCase())) return false
      }
      return true
    })
    .sort((a, b) => {
      const aa = a.date || ''
      const bb = b.date || ''
      return sortNewest ? bb.localeCompare(aa) : aa.localeCompare(bb)
    })

  const [actionStatus, setActionStatus] = useState('')
  const truncatedAccounts = view.type === 'allInbox' ? Math.max(0, accounts.length - ALL_INBOX_ACCOUNT_LIMIT) : 0
  const unreadCount = visible.filter((m) => !m.is_read).length
  const loading = view.type === 'accountFolder' ? singleQuery.isLoading : accountsQuery.isLoading || allQueries.some((q) => q.isLoading)
  const error = view.type === 'accountFolder' ? singleQuery.error : allQueries.find((q) => q.error)?.error

  const title = view.type === 'allInbox'
    ? '所有收件箱'
    : `${view.email} · ${view.folder === 'junkemail' ? '垃圾邮件' : view.folder === 'deleteditems' ? '废纸篓' : view.folder === 'all' ? '全部' : '收件箱'}`

  async function markAll() {
    const groups = new Map<string, MailItem[]>()
    visible.filter((m) => !m.is_read && m.id).forEach((m) => {
      const list = groups.get(m.accountEmail) || []
      list.push(m)
      groups.set(m.accountEmail, list)
    })
    const results = await Promise.allSettled([...groups.entries()].map(async ([email, items]) => ensureSuccess(await markEmailsRead(email, items, items[0]?.folder || 'inbox'), `${email} 标记失败`)))
    const failed = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected')
    setActionStatus(failed.length ? `部分账户标记失败：${failed.map((r) => errorMessage(r.reason)).join('；')}` : '')
    await queryClient.invalidateQueries({ queryKey: ['emails'] })
  }

  async function deleteSelected() {
    const chosen = visible.filter((m) => selectedIds.includes(`${m.accountEmail}:${m.id}`))
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
      selectAll(chosen.filter((m) => failedEmails.has(m.accountEmail)).map((m) => `${m.accountEmail}:${m.id}`))
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
            <div className="list-title">{title}</div>
            <div className="list-count">{loading ? '正在拉取邮件…' : `${visible.length} 封邮件 · ${unreadCount} 封未读`}</div>
          </div>
          <div className="list-primary-actions">
            <button className="list-primary-btn" title="账户导航" onClick={toggleMobileSidebar}>
              <Menu size={16} />
            </button>
            <button className="list-primary-btn" title="写邮件" onClick={() => openCompose('new')}>
              <PenSquare size={16} />
            </button>
            <button
              className="list-primary-btn"
              title="刷新"
              onClick={() => queryClient.invalidateQueries({ queryKey: ['emails'] })}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        <label className="list-search">
          <Search size={16} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索所有邮箱" aria-label="搜索所有邮箱" />
          {search && <button className="list-primary-btn" title="清除搜索" aria-label="清除搜索" onClick={() => setSearch('')}><X size={14} /></button>}
        </label>
        <div className="list-controls">
          <div className="segmented">
            {(['all', 'unread', 'flagged'] as const).map((f) => (
              <button key={f} className={`segment-btn ${listFilter === f ? 'active' : ''}`} onClick={() => setListFilter(f)}>
                {f === 'all' ? '全部' : f === 'unread' ? '未读' : '已标记'}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <button className="mark-all-btn" onClick={markAll} disabled={unreadCount === 0} title="将当前列表中的邮件全部标为已读">
              <CheckCircle size={13} />
              <span className="mark-label">全部已读</span>
            </button>
            <button className="sort-btn" onClick={() => selectAll(visible.map((m) => `${m.accountEmail}:${m.id}`))} title="选择当前列表">
              全选
            </button>
            {selectedIds.length > 0 && (
              <button className="sort-btn" onClick={deleteSelected} title="删除所选">
                删除所选
              </button>
            )}
            {selectedIds.length > 0 && (
              <button className="sort-btn" onClick={clearSelected} title="取消选择">
                取消 {selectedIds.length}
              </button>
            )}
            <button className="sort-btn" onClick={toggleSort} title="切换邮件排序">
              <SortAsc size={14} />
              <span>{sortNewest ? '最新优先' : '最早优先'}</span>
            </button>
            <button className="list-more-btn" title="更多">
              <MoreHorizontal size={16} />
            </button>
          </div>
        </div>
      </div>
      <div className="message-list">
        {truncatedAccounts > 0 && (
          <div role="note" style={{ padding: '8px 14px', fontSize: 11, color: 'var(--muted)', borderBottom: '1px solid var(--line)' }}>
            所有收件箱仅汇总前 {ALL_INBOX_ACCOUNT_LIMIT} 个账户，另有 {truncatedAccounts} 个账户未包含；请在左侧选择单个账户查看。
          </div>
        )}
        {actionStatus && <div role="status" style={{ padding: '8px 14px', fontSize: 12, color: actionStatus.includes('失败') ? 'var(--red)' : 'var(--muted)' }}>{actionStatus}</div>}
        {error && <div style={{ padding: 20, color: 'var(--red)', fontSize: 12 }}>{errorMessage(error, String(error))}</div>}
        {!loading && visible.length === 0 && (
          <div style={{ padding: 45, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
            {accounts.length === 0 ? '还没有账户。在设置或旧版界面中添加账户后，这里会显示真实邮件。' : '没有找到邮件'}
          </div>
        )}
        {visible.map((m) => {
          const key = `${m.accountEmail}:${m.id}`
          return (
            <article
              key={key}
              className={`message-row ${selectedKey === key ? 'selected' : ''} ${!m.is_read ? 'unread' : ''} ${selectedIds.includes(key) ? 'checked' : ''}`}
              onClick={() => {
                setSelectedKey(key)
                if (window.innerWidth <= 760) setMobileView('detail')
              }}
            >
              <button
                className="message-check"
                style={{ opacity: selectedIds.includes(key) ? 1 : undefined }}
                onClick={(e) => { e.stopPropagation(); toggleSelected(key) }}
                title="选择邮件"
              >
                {selectedIds.includes(key) ? '✓' : ''}
              </button>
              <div className="avatar" style={{ background: '#6d8fd1' }}>{(m.from || '?').slice(0, 1).toUpperCase()}</div>
              <div className="message-content">
                <div className="message-top">
                  <span className="sender">
                    {!m.is_read && <span className="unread-dot" style={{ display: 'inline-block', marginRight: 5, verticalAlign: 'middle' }} />}
                    {m.from}
                  </span>
                  <time className="message-date">{formatWhen(m.date)}</time>
                </div>
                <div className="subject">{m.subject}</div>
                <div className="preview">{m.body_preview}</div>
                <div className="message-bottom">
                  <span className="mail-account-tag">{m.accountEmail}</span>
                  {m.has_attachments && <Paperclip size={12} />}
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
