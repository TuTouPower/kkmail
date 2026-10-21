import { memo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Inbox, MailOpen, Send, Settings, PanelLeft, AlertCircle } from 'lucide-react'
import { apiRequest } from '../api/client'
import { fetchAccounts, fetchGroups, queryKeys } from '../api/queries'
import { fetchGlobalStats } from '../api/mailCore'
import { providerBadge, providerColor, useMailStore, type FavoriteCategory } from '../store/mailStore'
import { useIsWide } from '../lib/viewport'

interface FolderStatsItem {
  unread_count?: number
  total_count?: number
  role?: string
}

async function fetchAccountFolders(accountId: string, signal?: AbortSignal): Promise<number> {
  let res: unknown
  try {
    res = await apiRequest(`/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`, { signal })
  } catch {
    return 0
  }
  const folders: FolderStatsItem[] = Array.isArray(res)
    ? res
    : Array.isArray((res as { folders?: unknown })?.folders)
      ? (res as { folders: FolderStatsItem[] }).folders
      : []
  const inboxFolder = folders.find((f) => f.role === 'inbox')
  return inboxFolder?.unread_count ?? folders.reduce((sum, f) => sum + (f.unread_count || 0), 0)
}

const Sidebar = memo(function Sidebar() {
  const view = useMailStore((s) => s.view)
  const setView = useMailStore((s) => s.setView)
  const collapsedGroups = useMailStore((s) => s.collapsedGroups)
  const toggleGroup = useMailStore((s) => s.toggleGroup)
  const toggleSidebar = useMailStore((s) => s.toggleSidebar)
  const closeMobileSidebar = useMailStore((s) => s.closeMobileSidebar)
  const listFilter = useMailStore((s) => s.listFilter)
  const openSettings = useMailStore((s) => s.openSettings)
  const setListFilter = useMailStore((s) => s.setListFilter)
  const wide = useIsWide()
  const [expandedFavorites, setExpandedFavorites] = useState<Record<FavoriteCategory, boolean>>({
    inbox: false,
    unread: false,
    sent: false,
  })
  const toggleFavorite = (cat: FavoriteCategory) => {
    setExpandedFavorites((prev) => ({ ...prev, [cat]: !prev[cat] }))
  }

  const groupsQuery = useQuery({ queryKey: queryKeys.groups, queryFn: fetchGroups })
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })

  const groups = groupsQuery.data || []
  const accounts = accountsQuery.data || []

  const statsQuery = useQuery({
    queryKey: queryKeys.stats,
    queryFn: async ({ signal }) => {
      try {
        const globalStats = await fetchGlobalStats(signal)
        const statsMap = new Map<string, number>()
        for (const item of globalStats.accounts) {
          statsMap.set(item.account_id, item.unread_count)
        }
        return {
          totalUnread: globalStats.total_unread,
          byAccount: statsMap,
        }
      } catch {
        const statsMap = new Map<string, number>()
        await Promise.all(
          accounts.map(async (a) => {
            const count = await fetchAccountFolders(a.id, signal)
            statsMap.set(a.id, count)
          }),
        )
        const total = [...statsMap.values()].reduce((n, c) => n + c, 0)
        return {
          totalUnread: total,
          byAccount: statsMap,
        }
      }
    },
    enabled: accounts.length > 0,
  })

  const unreadByAccount = statsQuery.data?.byAccount ?? new Map<string, number>()
  const allInboxUnread = statsQuery.data?.totalUnread ?? 0
  const inAllInbox = view.type === 'allInbox'
  const groupIds = new Set(groups.map((g) => g.id))
  const ungroupedAccounts = accounts.filter((a) => !a.group_id || !groupIds.has(a.group_id))
  const grouped = groups.length
    ? [
        ...groups.map((g) => ({ group: g, members: accounts.filter((a) => a.group_id === g.id) })),
        ...(ungroupedAccounts.length
          ? [{ group: { id: '__ungrouped__', name: '未分组账户' }, members: ungroupedAccounts }]
          : []),
      ]
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
          {[
            { category: 'inbox' as const, label: '所有收件箱', icon: Inbox, showBadges: true },
            { category: 'unread' as const, label: '所有未读', icon: MailOpen, showBadges: false },
            { category: 'sent' as const, label: '所有已发邮件', icon: Send, showBadges: false },
          ].map(({ category: cat, label, icon: Icon, showBadges }) => {
            const isExpanded = !!expandedFavorites[cat]
            const isTopActive =
              (view.type === 'favorite' && view.category === cat && !view.accountId) ||
              (cat === 'inbox' && inAllInbox && listFilter === 'all') ||
              (cat === 'unread' && inAllInbox && listFilter === 'unread')

            return (
              <div key={cat} className={`favorite-category favorite-category-${cat}`}>
                <div className={`side-item-group ${isTopActive ? 'active' : ''}`}>
                  <button
                    type="button"
                    className="category-toggle group-toggle"
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleFavorite(cat)
                    }}
                    title={isExpanded ? `折叠 ${label}` : `展开 ${label}`}
                    aria-label={isExpanded ? `折叠` : `展开`}
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  <button
                    type="button"
                    className={`side-item category-btn ${isTopActive ? 'active' : ''}`}
                    onClick={() => {
                      setView({ type: 'favorite', category: cat })
                      if (cat === 'unread') {
                        setListFilter('unread')
                      } else {
                        setListFilter('all')
                      }
                    }}
                  >
                    <Icon size={17} />
                    <span className="side-name">{label}</span>
                    {showBadges && allInboxUnread > 0 && (
                      <span className="side-count unread-badge" title={`${allInboxUnread} 封未读`} aria-label={`${allInboxUnread} 封未读`}>
                        {allInboxUnread}
                      </span>
                    )}
                  </button>
                </div>

                {isExpanded && (
                  <div className="favorite-accounts">
                    {accounts.map((a) => {
                      const isSubActive =
                        view.type === 'favorite' &&
                        view.category === cat &&
                        view.accountId === a.id
                      const unread = unreadByAccount.get(a.id)

                      return (
                        <div key={a.id} className="favorite-account-row">
                          <button
                            type="button"
                            className={`account-button category-account-btn ${isSubActive ? 'active' : ''}`}
                            onClick={() => {
                              setView({ type: 'favorite', category: cat, accountId: a.id, email: a.email })
                              if (cat === 'unread') {
                                setListFilter('unread')
                              } else {
                                setListFilter('all')
                              }
                            }}
                            title={a.email}
                          >
                            <span className="account-dot" style={{ background: a.group_color || providerColor(a.provider, a.account_type) }}>
                              {providerBadge(a.provider, a.account_type)}
                            </span>
                            <span className="account-email">{a.email}</span>
                            {showBadges && !!unread && (
                              <span className="side-count unread-badge" aria-label={`${unread} 封未读`}>
                                {unread}
                              </span>
                            )}
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
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
                  <button
                    className="group-toggle"
                    onClick={() => toggleGroup(key)}
                    title={collapsed ? `展开分组 ${group.name}` : `折叠分组 ${group.name}`}
                    aria-label={collapsed ? `展开分组 ${group.name}` : `折叠分组 ${group.name}`}
                    aria-expanded={!collapsed}
                  >
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
})

export default Sidebar
