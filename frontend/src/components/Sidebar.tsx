import { useQueries, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Inbox, MailOpen, Flag, Settings, PanelLeft, AlertCircle } from 'lucide-react'
import { ALL_INBOX_ACCOUNT_LIMIT, fetchAccounts, fetchEmails, fetchGroups, queryKeys, type MailItem } from '../api/queries'
import { FOLDERS, providerBadge, providerColor, useMailStore } from '../store/mailStore'
import SettingsModal from './SettingsModal'
import { useState } from 'react'

export default function Sidebar() {
  const {
    view,
    setView,
    collapsedGroups,
    toggleGroup,
    collapsedAccounts,
    toggleAccount,
    toggleSidebar,
    closeMobileSidebar,
    listFilter,
    setListFilter,
  } = useMailStore()
  const [settingsOpen, setSettingsOpen] = useState(false)

  const groupsQuery = useQuery({ queryKey: queryKeys.groups, queryFn: fetchGroups })
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })

  const groups = groupsQuery.data || []
  const accounts = accountsQuery.data || []
  // Read-only observers of the cached inbox lists (never fetch from here), so
  // badges follow the list exactly, including optimistic "read" updates.
  const inboxCaches = useQueries({
    queries: accounts.map((a) => ({
      queryKey: queryKeys.emails(a.email, 'inbox'),
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchEmails(a.email, 'inbox', a.id, signal),
      enabled: false,
    })),
  })
  const unreadByAccount = new Map<string, number | undefined>()
  accounts.forEach((a, i) => {
    const data = inboxCaches[i]?.data as MailItem[] | undefined
    unreadByAccount.set(a.email, data ? data.filter((m) => !m.is_read).length : undefined)
  })
  const allInboxUnread = accounts.slice(0, ALL_INBOX_ACCOUNT_LIMIT).reduce((n, a) => n + (unreadByAccount.get(a.email) || 0), 0)
  const inAllInbox = view.type === 'allInbox'
  const grouped = groups.length
    ? groups.map((g) => ({ group: g, members: accounts.filter((a) => a.group_id === g.id) }))
    : [{ group: { id: 0, name: '全部账户' }, members: accounts }]

  return (
    <aside className="sidebar" aria-label="邮箱导航">
      <div className="sidebar-head">
        <button className="sidebar-toggle" onClick={toggleSidebar} title="折叠侧边栏" aria-label="折叠或展开侧边栏">
          <PanelLeft size={18} />
        </button>
      </div>
      <div className="sidebar-scroll">
        <div className="side-section">
          <div className="section-label"><span>个人收藏</span></div>
          <button className={`side-item ${inAllInbox && listFilter === 'all' ? 'active' : ''}`} onClick={() => { setView({ type: 'allInbox' }); setListFilter('all'); closeMobileSidebar() }}>
            <Inbox size={17} />
            <span className="side-name">所有收件箱</span>
            {allInboxUnread > 0 && <span className="side-count unread-badge" title={`${allInboxUnread} 封未读`} aria-label={`${allInboxUnread} 封未读`}>{allInboxUnread}</span>}
          </button>
          <button className={`side-item ${inAllInbox && listFilter === 'unread' ? 'active' : ''}`} onClick={() => { setView({ type: 'allInbox' }); setListFilter('unread'); closeMobileSidebar() }}>
            <MailOpen size={17} />
            <span className="side-name">未读邮件</span>
          </button>
          <button className={`side-item ${inAllInbox && listFilter === 'flagged' ? 'active' : ''}`} onClick={() => { setView({ type: 'allInbox' }); setListFilter('flagged'); closeMobileSidebar() }}>
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
                  const accKey = String(a.id)
                  const isCollapsed = collapsedAccounts.includes(accKey)
                  const selected = view.type === 'accountFolder' && view.accountId === a.id && view.folder === 'inbox'
                  return (
                    <div key={a.id}>
                      <div className="account-row">
                        <button className="account-expand" onClick={() => toggleAccount(accKey)} aria-label={isCollapsed ? `展开 ${a.email}` : `折叠 ${a.email}`} aria-expanded={!isCollapsed}>
                          {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                        </button>
                        <button
                          className={`account-button ${selected ? 'active' : ''}`}
                          onClick={() => { setView({ type: 'accountFolder', accountId: a.id, email: a.email, folder: 'inbox' }); closeMobileSidebar() }}
                          title={a.email}
                        >
                          <span className="account-dot" style={{ background: a.group_color || providerColor(a.provider, a.account_type) }}>
                            {providerBadge(a.provider, a.account_type)}
                          </span>
                          <span className="account-email">{a.email}</span>
                          {!!unreadByAccount.get(a.email) && <span className="side-count unread-badge" aria-label={`${unreadByAccount.get(a.email)} 封未读`}>{unreadByAccount.get(a.email)}</span>}
                        </button>
                      </div>
                      {!isCollapsed && (
                        <div className="folder-tree">
                          {FOLDERS.map((f) => {
                            const active = view.type === 'accountFolder' && view.accountId === a.id && view.folder === f.api
                            return (
                              <button
                                key={f.id}
                                className={`side-item ${active ? 'active' : ''}`}
                                onClick={() => { setView({ type: 'accountFolder', accountId: a.id, email: a.email, folder: f.api }); closeMobileSidebar() }}
                              >
                                <Inbox size={15} />
                                <span className="side-name">{f.label}</span>
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
        <div style={{ padding: '5px 9px 4px', color: 'var(--muted)', fontSize: 10, lineHeight: 1.6 }}>
          账户与邮件来自现有 Flask API。<br />
          收件箱 / 垃圾邮件 / 废纸篓为上游当前支持的实时文件夹。
        </div>
      </div>
      <div className="sidebar-footer">
        <button className="footer-btn" onClick={() => setSettingsOpen(true)}>
          <Settings size={17} />
          <span>设置</span>
        </button>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </aside>
  )
}
