import { memo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Inbox,
  MailOpen,
  Send,
  Settings,
  PanelLeft,
  AlertCircle,
  FileText,
  Trash2,
  ShieldAlert,
  Folder as FolderIcon,
  Archive,
} from 'lucide-react'
import { apiRequest } from '../api/client'
import { fetchAccounts, fetchGroups, queryKeys } from '../api/queries'
import { fetchGlobalStats } from '../api/mailCore'
import { errorMessage } from '../lib/actions'
import { useMailStore, type FavoriteCategory } from '../store/mailStore'
import { useIsWide } from '../lib/viewport'
import AccountIcon from './AccountIcon'

interface FolderStatsItem {
  folder_id?: string
  unread_count?: number
  total_count?: number
  role?: string
  name?: string
  remote_id?: string
  parent_remote_id?: string | null
}

const ROLE_PRIORITY: Record<string, number> = {
  inbox: 1,
  sent: 2,
  drafts: 3,
  trash: 4,
  junk: 5,
  archive: 6,
}

function getRolePriority(role: string): number {
  return ROLE_PRIORITY[role] ?? 7
}

function getStandardName(role: string, rawName: string): string {
  switch (role) {
    case 'inbox':
      return '收件箱'
    case 'sent':
      return '已发送'
    case 'drafts':
      return '草稿箱'
    case 'trash':
      return '废纸篓'
    case 'junk':
      return '垃圾邮件'
    case 'archive':
      return '归档'
    default:
      return rawName
  }
}

function getFolderIcon(role: string) {
  switch (role) {
    case 'inbox':
      return Inbox
    case 'sent':
      return Send
    case 'drafts':
      return FileText
    case 'trash':
      return Trash2
    case 'junk':
      return ShieldAlert
    case 'archive':
      return Archive
    default:
      return FolderIcon
  }
}

interface AccountFolderTreeProps {
  accountId: string
  accountEmail: string
}

function AccountFolderTree({ accountId, accountEmail }: AccountFolderTreeProps) {
  const view = useMailStore((s) => s.view)
  const setView = useMailStore((s) => s.setView)
  const setListFilter = useMailStore((s) => s.setListFilter)

  const foldersQuery = useQuery({
    queryKey: ['mail-core', 'account-folders', accountId],
    queryFn: async ({ signal }) => {
      const res = await apiRequest<{ account_id: string; folders: FolderStatsItem[] }>(
        `/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`,
        { signal },
      )
      return res.folders || []
    },
    retry: false,
  })

  if (foldersQuery.isLoading) {
    return (
      <div className="folder-tree-status" style={{ padding: '4px 12px 4px 34px', fontSize: 12, color: 'var(--muted)' }}>
        正在加载文件夹…
      </div>
    )
  }

  if (foldersQuery.isError || !foldersQuery.data) {
    return (
      <div className="folder-tree-status" style={{ padding: '4px 12px 4px 34px', fontSize: 12, color: 'var(--red)' }}>
        文件夹加载失败
      </div>
    )
  }

  const folders = foldersQuery.data
  const folderMap = new Map<string, FolderStatsItem>()
  for (const f of folders) {
    if (f.remote_id) folderMap.set(f.remote_id, f)
  }

  const childrenMap = new Map<string, FolderStatsItem[]>()
  const roots: FolderStatsItem[] = []

  for (const f of folders) {
    if (f.parent_remote_id && folderMap.has(f.parent_remote_id)) {
      const list = childrenMap.get(f.parent_remote_id) || []
      list.push(f)
      childrenMap.set(f.parent_remote_id, list)
    } else {
      roots.push(f)
    }
  }

  const sortFolders = (list: FolderStatsItem[]) => {
    return [...list].sort((a, b) => {
      const pA = getRolePriority(a.role || 'other')
      const pB = getRolePriority(b.role || 'other')
      if (pA !== pB) return pA - pB
      return (a.name || '').localeCompare(b.name || '', 'zh-CN')
    })
  }

  const renderTree = (items: FolderStatsItem[], level: number = 0) => {
    const sorted = sortFolders(items)
    return sorted.map((f) => {
      const role = f.role || 'other'
      const Icon = getFolderIcon(role)
      const displayName = getStandardName(role, f.name || '')
      const fid = String(f.folder_id || '')
      const isActive =
        view.type === 'folder' &&
        view.accountId === accountId &&
        view.folderId === fid
      const children = f.remote_id ? (childrenMap.get(f.remote_id) || []) : []

      return (
        <div key={fid || f.remote_id || f.name} className="folder-tree-row">
          <button
            type="button"
            className={`account-button category-account-btn folder-item-btn ${isActive ? 'active' : ''}`}
            style={{ paddingLeft: `${24 + level * 14}px` }}
            onClick={() => {
              setView({
                type: 'folder',
                accountId,
                email: accountEmail,
                folderId: fid,
                folderName: displayName,
                folderRole: role,
              })
              setListFilter('all')
            }}
            title={displayName}
          >
            <Icon size={14} style={{ flexShrink: 0 }} />
            <span className="account-email">{displayName}</span>
            {typeof f.unread_count === 'number' && f.unread_count > 0 && (
              <span className="side-count unread-badge">{f.unread_count}</span>
            )}
          </button>
          {children.length > 0 && renderTree(children, level + 1)}
        </div>
      )
    })
  }

  return <div className="account-folders" style={{ paddingLeft: '8px' }}>{renderTree(roots, 0)}</div>
}

async function fetchAccountFolders(accountId: string, signal?: AbortSignal): Promise<number | null> {
  const res = await apiRequest(`/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`, { signal })
  const folders: FolderStatsItem[] = Array.isArray(res)
    ? res
    : Array.isArray((res as { folders?: unknown })?.folders)
      ? (res as { folders: FolderStatsItem[] }).folders
      : []
  const inboxFolder = folders.find((f) => f.role === 'inbox')
  return typeof inboxFolder?.unread_count === 'number' ? inboxFolder.unread_count : null
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
    drafts: false,
    trash: false,
    junk: false,
  })
  const toggleFavorite = (cat: FavoriteCategory) => {
    setExpandedFavorites((prev) => ({ ...prev, [cat]: !prev[cat] }))
  }

  const [expandedAccounts, setExpandedAccounts] = useState<Record<string, boolean>>({})
  const toggleAccount = (id: string) => {
    setExpandedAccounts((prev) => ({ ...prev, [id]: !prev[id] }))
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
        const statsMap = new Map<string, number | null>()
        for (const item of globalStats.accounts) {
          statsMap.set(item.account_id, item.unread_count)
        }
        return {
          totalUnread: globalStats.total_unread as number | null,
          byAccount: statsMap,
        }
      } catch {
        const statsMap = new Map<string, number | null>()
        let anyFailed = false
        let total = 0

        await Promise.all(
          accounts.map(async (a) => {
            try {
              const count = await fetchAccountFolders(a.id, signal)
              statsMap.set(a.id, count)
              if (count === null) {
                anyFailed = true
              } else {
                total += count
              }
            } catch {
              anyFailed = true
              statsMap.set(a.id, null)
            }
          }),
        )

        return {
          totalUnread: anyFailed ? null : total,
          byAccount: statsMap,
        }
      }
    },
    enabled: accounts.length > 0,
  })

  const statsData = statsQuery.data
  const unreadByAccount = statsData?.byAccount ?? new Map<string, number | null>()
  const allInboxUnread = statsData ? statsData.totalUnread : (statsQuery.isError ? null : 0)
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
          data-ui="SB01"
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
          <div data-ui="SB02" className="section-label"><span>个人收藏</span></div>
          {[
            { category: 'inbox' as const, label: '所有收件', icon: Inbox, showBadges: true, uiId: 'SB03' },
            { category: 'unread' as const, label: '所有未读', icon: MailOpen, showBadges: false, uiId: 'SB04' },
            { category: 'sent' as const, label: '已发邮件', icon: Send, showBadges: false, uiId: 'SB05' },
            { category: 'drafts' as const, label: '草稿箱', icon: FileText, showBadges: false, uiId: 'SB06' },
            { category: 'trash' as const, label: '废纸篓', icon: Trash2, showBadges: false, uiId: 'SB07' },
            { category: 'junk' as const, label: '垃圾邮件', icon: ShieldAlert, showBadges: false, uiId: 'SB08' },
          ].map(({ category: cat, label, icon: Icon, showBadges, uiId }) => {
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
                    data-ui={uiId}
                    type="button"
                    className={`side-item category-btn ${isTopActive ? 'active' : ''}`}
                    aria-label={cat === 'inbox' ? '所有收件箱' : label}
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
                    {showBadges && (
                      allInboxUnread === null ? (
                        <span className="side-count unread-badge unread-badge-unknown" title="未读数获取失败" aria-label="未读数未知">
                          -
                        </span>
                      ) : allInboxUnread > 0 ? (
                        <span className="side-count unread-badge" title={`${allInboxUnread} 封未读`} aria-label={`${allInboxUnread} 封未读`}>
                          {allInboxUnread}
                        </span>
                      ) : null
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
                            <AccountIcon
                              email={a.email}
                              provider={a.provider}
                              accountType={a.account_type}
                              groupColor={a.group_color}
                            />
                            <span className="account-email">{a.email}</span>
                            {showBadges && (
                              unread === null ? (
                                <span className="side-count unread-badge unread-badge-unknown" title="未读数获取失败" aria-label="未读数未知">
                                  -
                                </span>
                              ) : (typeof unread === 'number' && unread > 0) ? (
                                <span className="side-count unread-badge" aria-label={`${unread} 封未读`}>
                                  {unread}
                                </span>
                              ) : null
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
          <div data-ui="SB09" className="section-label"><span>邮箱账户</span></div>
          {(groupsQuery.isLoading || accountsQuery.isLoading) && (
            <div style={{ padding: '8px 10px', color: 'var(--muted)', fontSize: 12 }}>正在加载账户…</div>
          )}
          {(groupsQuery.error || accountsQuery.error || statsQuery.error) && (
            <div
              style={{
                padding: '8px 10px',
                color: 'var(--red)',
                fontSize: 12,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <AlertCircle size={14} style={{ flexShrink: 0 }} />
                <span>{errorMessage(accountsQuery.error || groupsQuery.error || statsQuery.error, '账户加载失败')}</span>
              </div>
              <button
                type="button"
                className="account-error-retry"
                onClick={() => {
                  void accountsQuery.refetch()
                  void groupsQuery.refetch()
                  void statsQuery.refetch()
                }}
                style={{
                  alignSelf: 'flex-start',
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 4,
                  border: '1px solid var(--line)',
                  background: 'var(--surface-2)',
                  color: 'var(--text)',
                  cursor: 'pointer',
                }}
              >
                重试
              </button>
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
                  const isAccountExpanded = !!expandedAccounts[a.id]
                  const unread = unreadByAccount.get(a.id)
                  return (
                    <div data-ui="SB10" className="account-row" key={a.id}>
                      <div className={`side-item-group ${selected ? 'active' : ''}`}>
                        <button
                          type="button"
                          className="category-toggle group-toggle account-folders-toggle"
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleAccount(a.id)
                          }}
                          title={isAccountExpanded ? `折叠文件夹` : `展开文件夹`}
                          aria-label={isAccountExpanded ? `折叠文件夹` : `展开文件夹`}
                          aria-expanded={isAccountExpanded}
                        >
                          {isAccountExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                        <button
                          className={`account-button ${selected ? 'active' : ''}`}
                          onClick={() => { setView({ type: 'account', accountId: a.id, email: a.email }) }}
                          title={a.email}
                        >
                          <AccountIcon
                            email={a.email}
                            provider={a.provider}
                            accountType={a.account_type}
                            groupColor={a.group_color}
                          />
                          <span className="account-email">{a.email}</span>
                          {unread === null ? (
                            <span className="side-count unread-badge unread-badge-unknown" title="未读数获取失败" aria-label="未读数未知">
                              -
                            </span>
                          ) : (typeof unread === 'number' && unread > 0) ? (
                            <span className="side-count unread-badge" aria-label={`${unread} 封未读`}>
                              {unread}
                            </span>
                          ) : null}
                        </button>
                      </div>
                      {isAccountExpanded && (
                        <AccountFolderTree accountId={a.id} accountEmail={a.email} />
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
      <div className="sidebar-footer">
        <button data-ui="SB11" className="footer-btn" onClick={() => openSettings()}>
          <Settings size={17} />
          <span>设置</span>
        </button>
      </div>
    </aside>
  )
})

export default Sidebar
