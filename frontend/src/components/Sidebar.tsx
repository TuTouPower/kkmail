import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Inbox, MailOpen, Flag, Settings, PanelLeft, AlertCircle } from 'lucide-react'
import { fetchAccounts, fetchGroups, queryKeys, type MailItem } from '../api/queries'
import { providerBadge, providerColor, useMailStore } from '../store/mailStore'
import { useIsWide } from '../lib/viewport'

export default function Sidebar() {
  const {
    view,
    setView,
    collapsedGroups,
    toggleGroup,
    toggleSidebar,
    closeMobileSidebar,
    listFilter,
    openSmartView,
    openSettings,
  } = useMailStore()
  const wide = useIsWide()

  const groupsQuery = useQuery({ queryKey: queryKeys.groups, queryFn: fetchGroups })
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })

  const groups = groupsQuery.data || []
  const accounts = accountsQuery.data || []
  // Unread badges are derived from the cached unified inbox page (populated by MessageList).
  const inboxCache = useQuery({
    queryKey: queryKeys.inbox('all'),
    queryFn: async () => [] as MailItem[],
    enabled: false,
  })
  const inboxRows = (inboxCache.data || []) as MailItem[]
  const unreadByAccount = new Map<string, number>()
  for (const m of inboxRows) {
    if (m.is_read) continue
    if (m.accountId) unreadByAccount.set(m.accountId, (unreadByAccount.get(m.accountId) || 0) + 1)
  }
  const allInboxUnread = [...unreadByAccount.values()].reduce((n, c) => n + c, 0)
  const inAllInbox = view.type === 'allInbox'
  const grouped = groups.length
    ? groups.map((g) => ({ group: g, members: accounts.filter((a) => a.group_id === g.id) }))
    : [{ group: { id: '0', name: '全部账户' }, members: accounts }]

  return (
    <aside className="sidebar" aria-label="邮箱导航" role={wide ? undefined : 'dialog'} aria-modal={wide ? undefined : true}>
      <div className="sidebar-head">
        <button
          className="sidebar-toggle"
          // On mobile the sidebar is an overlay drawer: this button closes it.
          onClick={wide ? toggleSidebar : closeMobileSidebar}
          title={wide ? '折叠侧边栏' : '关闭侧边栏'}
          aria-label={wide ? '折叠或展开侧边栏' : '关闭侧边栏'}
        >
          <PanelLeft size={18} />
        </button>
      </div>
      <div className="sidebar-scroll">
        <div className="side-section">
          <div className="section-label"><span>个人收藏</span></div>
          <button className={`side-item ${inAllInbox && listFilter === 'all' ? 'active' : ''}`} onClick={() => openSmartView('all')}>
            <Inbox size={17} />
            <span className="side-name">所有收件箱</span>
            {allInboxUnread > 0 && <span className="side-count unread-badge" title={`${allInboxUnread} 封未读`} aria-label={`${allInboxUnread} 封未读`}>{allInboxUnread}</span>}
          </button>
          <button className={`side-item ${inAllInbox && listFilter === 'unread' ? 'active' : ''}`} onClick={() => openSmartView('unread')}>
            <MailOpen size={17} />
            <span className="side-name">未读邮件</span>
          </button>
          <button className={`side-item ${inAllInbox && listFilter === 'flagged' ? 'active' : ''}`} onClick={() => openSmartView('flagged')}>
            <Flag size={17} />
            <span className="side-name">已标记</span>
          </button>
        </div>

        <div className="side-section">
          <div className="section-label"><span>邮箱账户</span></div>
          {(groupsQuery.isLoading || accountsQuery.isLoading) && (
            <div style={{ padding: '8px 10px', color: 'var(--muted)', fontSize: 12 }}>正在加载账户…</div>
          )}
          {(groupsQuery.error || accountsQuery.error) && (
            <div style={{ padding: '8px 10px', color: 'var(--red)', fontSize: 12, display: 'flex', gap: 6 }}>
              <AlertCircle size={14} /> 账户加载失败，请确认已登录且后端可用
            </div>
          )}
          {grouped.map(({ group, members }) => {
            const key = String(group.id)
            const collapsed = collapsedGroups.includes(key)
            return (
              <div className="account-group" key={key}>
                <div className="account-group-head">
                  <button className="group-toggle" onClick={() => toggleGroup(key)} aria-label={collapsed ? `展开分组 ${group.name}` : `折叠分组 ${group.name}`} aria-expanded={!collapsed}>
                    {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                  </button>
                  <span className="group-name">{group.name}</span>
                  <span className="group-count">{members.length}</span>
                </div>
                {!collapsed && members.map((a) => {
                  const selected = view.type === 'account' && view.accountId === a.id
                  const unread = unreadByAccount.get(a.id)
                  return (
                    <div className="account-row" key={a.id}>
                      <button
                        className={`account-button ${selected ? 'active' : ''}`}
                        onClick={() => { setView({ type: 'account', accountId: a.id, email: a.email }) }}
                        title={a.email}
                      >
                        <span className="account-dot" style={{ background: a.group_color || providerColor(a.provider, a.account_type) }}>
                          {providerBadge(a.provider, a.account_type)}
                        </span>
                        <span className="account-email">{a.email}</span>
                        {!!unread && <span className="side-count unread-badge" aria-label={`${unread} 封未读`}>{unread}</span>}
                      </button>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
      <div className="sidebar-footer">
        <button className="footer-btn" onClick={() => openSettings()}>
          <Settings size={17} />
          <span>设置</span>
        </button>
      </div>
    </aside>
  )
}
