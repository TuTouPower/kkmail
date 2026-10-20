import { Search, PenSquare, RefreshCw, CheckCircle, SortAsc, MoreHorizontal } from 'lucide-react'
import { useMailStore } from '../store/mailStore'

export default function MessageList() {
  const {
    messages,
    view,
    selectedId,
    setSelectedId,
    setMobileView,
    search,
    setSearch,
    listFilter,
    setListFilter,
    sortNewest,
    toggleSort,
    markAllVisibleRead,
  } = useMailStore()

  const visible = messages
    .filter((m) => {
      if (view.type === 'allInbox' && m.folder !== 'inbox') return false
      if (view.type === 'unread' && !m.unread) return false
      if (view.type === 'flagged' && !m.flagged) return false
      if (view.type === 'accountFolder' && (m.accountId !== view.accountId || (view.folder === 'important' ? !m.flagged : m.folder !== view.folder))) return false
      if (listFilter === 'unread' && !m.unread) return false
      if (listFilter === 'flagged' && !m.flagged) return false
      if (search) {
        const hay = [m.sender, m.subject, m.preview].join(' ').toLowerCase()
        if (!hay.includes(search.toLowerCase())) return false
      }
      return true
    })
    .sort((a, b) => {
      const aa = a.date + ' ' + a.time
      const bb = b.date + ' ' + b.time
      return sortNewest ? bb.localeCompare(aa) : aa.localeCompare(bb)
    })

  const unreadCount = visible.filter((m) => m.unread).length

  const title =
    view.type === 'allInbox'
      ? '所有收件箱'
      : view.type === 'unread'
      ? '未读邮件'
      : view.type === 'flagged'
      ? '已标记'
      : view.type === 'accountFolder'
      ? `${view.accountId} · ${view.folder}`
      : '邮件'

  return (
    <section className="list-pane" aria-label="邮件列表">
      <div className="list-header">
        <div className="list-title-row">
          <div className="list-heading">
            <div className="list-title">{title}</div>
            <div className="list-count">
              {visible.length} 封邮件 · {unreadCount} 封未读
            </div>
          </div>
          <div className="list-primary-actions">
            <button className="list-primary-btn" title="写邮件" onClick={() => alert('撰写邮件（演示）')}>
              <PenSquare size={16} />
            </button>
            <button className="list-primary-btn" title="刷新" onClick={() => alert('已刷新（演示）')}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        <label className="list-search">
          <Search size={16} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="搜索所有邮箱" aria-label="搜索所有邮箱" />
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
            <button className="mark-all-btn" onClick={markAllVisibleRead} disabled={unreadCount === 0} title="将当前列表中的邮件全部标为已读">
              <CheckCircle size={13} />
              <span className="mark-label">全部已读</span>
            </button>
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
        {visible.length === 0 ? (
          <div style={{ padding: 45, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>没有找到邮件</div>
        ) : (
          visible.map((m) => (
            <article
              key={m.id}
              className={`message-row ${selectedId === m.id ? 'selected' : ''} ${m.unread ? 'unread' : ''}`}
              onClick={() => {
                setSelectedId(m.id)
                if (window.innerWidth <= 760) setMobileView('detail')
              }}
            >
              <div className="avatar" style={{ background: m.color }}>
                {m.initial}
              </div>
              <div className="message-content">
                <div className="message-top">
                  <span className="sender">
                    {m.unread && <span className="unread-dot" style={{ display: 'inline-block', marginRight: 5, verticalAlign: 'middle' }} />}
                    {m.sender}
                  </span>
                  <time className="message-date">{m.time}</time>
                </div>
                <div className="subject">{m.subject}</div>
                <div className="preview">{m.preview}</div>
                <div className="message-bottom">
                  <span className="mail-account-tag">{m.accountId}</span>
                </div>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  )
}
