import { memo, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  ArrowDownWideNarrow,
  Check as CheckIcon,
  Inbox,
  MailOpen,
  Send,
  Settings,
  AlertCircle,
  FileText,
  Trash2,
  ShieldAlert,
  Folder as FolderIcon,
  Archive,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  X,
} from 'lucide-react'
import { api, apiRequest, type AccountSummary } from '../api/client'
import { fetchAccounts, fetchGroups, queryClient, queryKeys, resetGroupMailQueries, type GroupItem } from '../api/queries'
import type { AccountFolderStatsItemOut, AccountFolderStatsOut } from '../api/schemaTypes'
import { fetchGlobalStats } from '../api/mailCore'
import { confirmAction, errorMessage } from '../lib/actions'
import { useMailStore, type FavoriteCategory } from '../store/mailStore'
import { useIsWide } from '../lib/viewport'
import AccountIcon from './AccountIcon'
import CopyAddress from './CopyAddress'

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

async function fetchAccountFolders(accountId: string, signal?: AbortSignal): Promise<number | null> {
  const res = await apiRequest<AccountFolderStatsOut>(`/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`, { signal })
  const folders = res.folders
  const inboxFolders = folders.filter((folder) => folder.role === 'inbox')
  if (!inboxFolders.length || inboxFolders.some((folder) => folder.unread_count == null)) return null
  return inboxFolders.reduce((sum, folder) => sum + (folder.unread_count || 0), 0)
}

const CATEGORY_ITEMS: Array<{ category: FavoriteCategory; label: string; icon: typeof Inbox }> = [
  { category: 'inbox', label: '所有收件箱', icon: Inbox },
  { category: 'unread', label: '所有未读', icon: MailOpen },
  { category: 'sent', label: '已发邮件', icon: Send },
  { category: 'drafts', label: '草稿箱', icon: FileText },
  { category: 'trash', label: '废纸篓', icon: Trash2 },
  { category: 'junk', label: '垃圾邮件', icon: ShieldAlert },
]

type SidebarLayout = {
  groupIds: string[]
  masterIds: string[]
  ungroupedIds: string[]
  groupAccountIds: Record<string, string[]>
}

type DragPayload = { type: 'account'; accountId: string; sourceGroupId: string | null; sourceList: 'master' | 'group' } | { type: 'group'; groupId: string }

function compareAccounts(a: { email: string }, b: { email: string }): number {
  const aEmail = a.email.toLowerCase()
  const bEmail = b.email.toLowerCase()
  const aDomain = aEmail.slice(aEmail.lastIndexOf('@') + 1)
  const bDomain = bEmail.slice(bEmail.lastIndexOf('@') + 1)
  return aDomain.localeCompare(bDomain, 'en', { sensitivity: 'base' }) || aEmail.localeCompare(bEmail, 'en', { sensitivity: 'base' })
}

function matchesAccountSearch(account: AccountSummary, value: string): boolean {
  const query = value.trim().toLowerCase()
  if (!query) return true
  const email = account.email.toLowerCase()
  const domain = email.slice(email.lastIndexOf('@') + 1)
  return email.includes(query) || domain.includes(query) || (account.display_name || '').toLowerCase().includes(query)
}

function orderedMembers(accounts: AccountSummary[], groupId: string) {
  const members = accounts.filter((account) => account.group_id === groupId)
  if (members.some((account) => account.group_order != null)) {
    return members.sort((a, b) => (a.group_order ?? Number.MAX_SAFE_INTEGER) - (b.group_order ?? Number.MAX_SAFE_INTEGER) || compareAccounts(a, b))
  }
  return members.sort(compareAccounts)
}

function moveBefore(ids: string[], movedId: string, targetId?: string): string[] {
  const next = ids.filter((id) => id !== movedId)
  const targetIndex = targetId ? next.indexOf(targetId) : -1
  next.splice(targetIndex < 0 ? next.length : targetIndex, 0, movedId)
  return next
}

function sameMembership(a: SidebarLayout, b: SidebarLayout): boolean {
  const groups = new Set([...Object.keys(a.groupAccountIds), ...Object.keys(b.groupAccountIds)])
  const sameIds = (left: string[], right: string[]) => {
    if (left.length !== right.length) return false
    const leftIds = new Set(left)
    const rightIds = new Set(right)
    return leftIds.size === left.length && rightIds.size === right.length && [...leftIds].every((id) => rightIds.has(id))
  }
  if (!sameIds(a.ungroupedIds, b.ungroupedIds)) return false
  return [...groups].every((id) => sameIds(a.groupAccountIds[id] || [], b.groupAccountIds[id] || []))
}

interface AccountFolderTreeProps {
  accountId: string
  accountEmail: string
  unreadCount: number | null | undefined
  syncStatus?: string | null
}

function AccountFolders({ accountId, accountEmail, unreadCount, syncStatus }: AccountFolderTreeProps) {
  const view = useMailStore((s) => s.view)
  const setView = useMailStore((s) => s.setView)
  const setListFilter = useMailStore((s) => s.setListFilter)
  const foldersQuery = useQuery({
    queryKey: ['mail-core', 'account-folders', accountId],
    queryFn: async ({ signal }) => {
      const response = await apiRequest<AccountFolderStatsOut>(
        `/api/mail/accounts/${encodeURIComponent(accountId)}/folder-stats`, { signal },
      )
      return response.folders || []
    },
  })
  const folders = useMemo(() => foldersQuery.data || [], [foldersQuery.data])
  const folderDisplayNames = useMemo(() => {
    const groups = new Map<string, AccountFolderStatsItemOut[]>()
    for (const folder of folders) {
      const role = folder.role || 'other'
      const rawName = folder.name || folder.remote_id || folder.folder_id || ''
      const displayBase = getStandardName(role, rawName)
      const groupKey = JSON.stringify([role, displayBase])
      const group = groups.get(groupKey) || []
      group.push(folder)
      groups.set(groupKey, group)
    }

    const names = new Map<string, string>()
    for (const group of groups.values()) {
      const first = group[0]
      const role = first.role || 'other'
      const displayBase = getStandardName(role, first.name || first.remote_id || first.folder_id || '')
      const sameNameGroups = new Map<string, AccountFolderStatsItemOut[]>()
      for (const folder of group) {
        const rawName = folder.name || folder.remote_id || folder.folder_id || ''
        const sameName = sameNameGroups.get(rawName) || []
        sameName.push(folder)
        sameNameGroups.set(rawName, sameName)
      }

      for (const [rawName, sameNameFolders] of sameNameGroups) {
        const suffixes = new Map<string, string>()
        if (sameNameFolders.length > 1) {
          const ordered = [...sameNameFolders].sort((a, b) => (a.folder_id || '').localeCompare(b.folder_id || ''))
          ordered.forEach((folder, index) => suffixes.set(folder.folder_id, ` #${index + 1}`))
        }
        for (const folder of sameNameFolders) {
          const displayName = group.length > 1
            ? `${displayBase} · ${rawName}${suffixes.get(folder.folder_id) || ''}`
            : displayBase
          names.set(folder.folder_id, displayName)
        }
      }
    }
    return names
  }, [folders])

  if (foldersQuery.isLoading) return <div className="tree-folder-status" style={{ paddingLeft: '48px' }}>正在加载文件夹…</div>
  if (foldersQuery.isError || !foldersQuery.data) return <div className="tree-folder-status tree-error" style={{ paddingLeft: '48px' }}>文件夹加载失败 <button className="tree-retry" type="button" onClick={() => void foldersQuery.refetch()}>重试</button></div>

  if (folders.length === 0) {
    if (syncStatus === 'auth_failed' || syncStatus === 'failed') {
      return <div className="tree-folder-status tree-error" role="status" style={{ paddingLeft: '48px' }}>同步失败，请检查账户设置</div>
    }
    return <div className="tree-folder-status" style={{ paddingLeft: '48px' }}>暂无文件夹</div>
  }

  const folderMap = new Map(folders.filter((folder) => folder.remote_id).map((folder) => [folder.remote_id!, folder]))
  const childrenMap = new Map<string, AccountFolderStatsItemOut[]>()
  const roots: AccountFolderStatsItemOut[] = []
  for (const folder of foldersQuery.data) {
    if (folder.parent_remote_id && folderMap.has(folder.parent_remote_id)) {
      const children = childrenMap.get(folder.parent_remote_id) || []
      children.push(folder)
      childrenMap.set(folder.parent_remote_id, children)
    } else {
      roots.push(folder)
    }
  }

  const renderTree = (items: AccountFolderStatsItemOut[], level = 0): React.ReactNode => [...items].sort((a, b) => {
    const priority = getRolePriority(a.role || 'other') - getRolePriority(b.role || 'other')
    return priority || (a.name || '').localeCompare(b.name || '', 'zh-CN')
  }).map((folder) => {
    const role = folder.role || 'other'
    const notSelectable = folder.sync_status === 'paused'
    const rawName = folder.name || folder.remote_id || folder.folder_id || ''
    const displayBase = getStandardName(role, rawName)
    const displayName = folderDisplayNames.get(folder.folder_id) || displayBase
    const folderId = String(folder.folder_id || '')
    const active = view.type === 'folder' && view.accountId === accountId && view.folderId === folderId
    const children = folder.remote_id ? childrenMap.get(folder.remote_id) || [] : []
    const Icon = getFolderIcon(role)
    return (
      <div key={folderId || folder.remote_id || folder.name} className="tree-folder-node">
        <button
          type="button"
          disabled={notSelectable}
          className={`tree-nav-row tree-folder-row ${active ? 'active' : ''}`}
          style={{ paddingLeft: `${48 + level * 24}px` }}
          onClick={() => {
            setView({ type: 'folder', accountId, email: accountEmail, folderId, folderName: displayName, folderRole: role })
            setListFilter('all')
          }}
          title={notSelectable ? `${displayName}（目录容器）` : displayName}
        >
          <span className="tree-disclosure-slot" aria-hidden="true" />
          <Icon size={16} aria-hidden="true" />
          <span className="tree-label">{displayName}</span>
          {!notSelectable && (folder.unread_count === null ? <span className="side-count unread-badge unread-badge-unknown">-</span> : folder.unread_count ? <span className="side-count unread-badge">{folder.unread_count}</span> : null)}
        </button>
        {children.length > 0 && renderTree(children, level + 1)}
      </div>
    )
  })
  const syncFailed = syncStatus === 'auth_failed' || syncStatus === 'failed'
  return (
    <>
      {syncFailed && <div className="tree-folder-status tree-error" role="status" style={{ paddingLeft: '48px' }}>同步失败，请检查账户设置</div>}
      <div className="tree-folder-list">
        <button type="button" className="tree-nav-row tree-folder-row" style={{ paddingLeft: '48px' }} onClick={() => {
          setView({ type: 'favorite', category: 'unread', accountId, email: accountEmail })
          setListFilter('unread')
        }}>
          <span className="tree-disclosure-slot" aria-hidden="true" />
          <MailOpen size={16} aria-hidden="true" /><span className="tree-label">未读邮件</span>
          {unreadCount === null ? <span className="side-count unread-badge unread-badge-unknown">-</span> : unreadCount && unreadCount > 0 ? <span className="side-count unread-badge">{unreadCount}</span> : null}
        </button>
        {renderTree(roots)}
      </div>
    </>
  )
}

function Sidebar() {
  const view = useMailStore((state) => state.view)
  const setView = useMailStore((state) => state.setView)
  const setSearch = useMailStore((state) => state.setSearch)
  const listFilter = useMailStore((state) => state.listFilter)
  const setListFilter = useMailStore((state) => state.setListFilter)
  const openSettings = useMailStore((state) => state.openSettings)
  const sidebarSections = useMailStore((state) => state.sidebarSections)
  const toggleSidebarSection = useMailStore((state) => state.toggleSidebarSection)
  const expandedGroups = useMailStore((state) => state.expandedSidebarGroups)
  const toggleExpandedGroup = useMailStore((state) => state.toggleSidebarGroup)
  const expandedAccounts = useMailStore((state) => state.expandedSidebarAccounts)
  const toggleExpandedAccount = useMailStore((state) => state.toggleSidebarAccount)
  const expandedCategories = useMailStore((state) => state.expandedSidebarCategories)
  const toggleExpandedCategory = useMailStore((state) => state.toggleSidebarCategory)
  const mobileSidebarOpen = useMailStore((state) => state.mobileSidebarOpen)
  const closeMobileSidebar = useMailStore((state) => state.closeMobileSidebar)
  const clearSelected = useMailStore((state) => state.clearSelected)
  const wide = useIsWide()
  const drawerOpen = mobileSidebarOpen && !wide
  const sidebarRef = useRef<HTMLElement | null>(null)
  const [openGroupSearchIds, setOpenGroupSearchIds] = useState<string[]>([])
  const [groupSearchTerms, setGroupSearchTerms] = useState<Record<string, string>>({})
  const [masterSearchOpen, setMasterSearchOpen] = useState(false)
  const [masterSearchTerm, setMasterSearchTerm] = useState('')
  const groupsQuery = useQuery({ queryKey: queryKeys.groups, queryFn: fetchGroups })
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const layoutQuery = useQuery({ queryKey: queryKeys.sidebarLayout, queryFn: () => api.getSidebarLayout() })
  const groups = groupsQuery.data || []
  const accounts = accountsQuery.data || []
  const enabledAccounts = useMemo(
    () => (accountsQuery.data || []).filter((account) => account.sync_enabled !== false),
    [accountsQuery.data],
  )
  const enabledAccountIds = useMemo(() => new Set(enabledAccounts.map((account) => account.id)), [enabledAccounts])
  const masterSearchActive = masterSearchTerm.trim().length > 0
  const masterSectionExpanded = sidebarSections.accountList || masterSearchOpen
  const filteredMasterAccounts = useMemo(
    () => masterSearchActive ? enabledAccounts.filter((account) => matchesAccountSearch(account, masterSearchTerm)) : enabledAccounts,
    [enabledAccounts, masterSearchActive, masterSearchTerm],
  )
  const selectedAccountId = view.type === 'account' || view.type === 'folder' || view.type === 'favorite'
    ? view.accountId
    : undefined
  useEffect(() => {
    if (!accountsQuery.isSuccess || !selectedAccountId || enabledAccountIds.has(selectedAccountId)) return
    setView({ type: 'allInbox' })
    setSearch('')
    clearSelected()
  }, [accountsQuery.isSuccess, clearSelected, enabledAccountIds, selectedAccountId, setSearch, setView])
  const visibleAccounts = enabledAccounts
  const [actionError, setActionError] = useState('')
  const [newGroupOpen, setNewGroupOpen] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null)
  const [editingGroupName, setEditingGroupName] = useState('')
  const [openMenuGroupId, setOpenMenuGroupId] = useState<string | null>(null)
  const [savingLayout, setSavingLayout] = useState(false)
  const [savingRename, setSavingRename] = useState(false)
  const dragPayload = useRef<DragPayload | null>(null)
  const layoutSaveInFlight = useRef(false)
  const renameSaveInFlight = useRef(false)
  const groupMenuTrigger = useRef<HTMLButtonElement | null>(null)
  const newGroupTrigger = useRef<HTMLButtonElement | null>(null)
  const masterSearchInputRef = useRef<HTMLInputElement | null>(null)
  const masterSearchTriggerRef = useRef<HTMLButtonElement | null>(null)
  const previousOpenGroupSearchIds = useRef<string[]>([])
  useEffect(() => {
    const newlyOpened = openGroupSearchIds.find((id) => !previousOpenGroupSearchIds.current.includes(id))
    previousOpenGroupSearchIds.current = openGroupSearchIds
    if (!newlyOpened) return
    const frame = requestAnimationFrame(() => {
      const input = [...document.querySelectorAll<HTMLInputElement>('[data-search-group-id]')]
        .find((element) => element.dataset.searchGroupId === newlyOpened)
      input?.focus()
    })
    return () => cancelAnimationFrame(frame)
  }, [openGroupSearchIds])
  useEffect(() => {
    if (!masterSearchOpen) return
    const frame = requestAnimationFrame(() => masterSearchInputRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [masterSearchOpen])
  useEffect(() => {
    if (!drawerOpen) return
    const sidebar = sidebarRef.current
    if (!sidebar) return

    const focusableElements = () => Array.from(sidebar.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => element.getAttribute('aria-hidden') !== 'true')

    const first = focusableElements()[0]
    ;(first ?? sidebar).focus()

    const trapTab = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const elements = focusableElements()
      if (elements.length === 0) {
        event.preventDefault()
        sidebar.focus()
        return
      }
      const activeIndex = elements.indexOf(document.activeElement as HTMLElement)
      if (event.shiftKey && activeIndex <= 0) {
        event.preventDefault()
        elements[elements.length - 1].focus()
      } else if (!event.shiftKey && (activeIndex < 0 || activeIndex === elements.length - 1)) {
        event.preventDefault()
        elements[0].focus()
      }
    }

    document.addEventListener('keydown', trapTab, true)
    return () => document.removeEventListener('keydown', trapTab, true)
  }, [drawerOpen])
  const statsQuery = useQuery({
    queryKey: queryKeys.stats,
    queryFn: async ({ signal }) => {
      try {
        const response = await fetchGlobalStats(signal)
        const byAccount = new Map(response.accounts
          .filter((entry) => enabledAccountIds.has(entry.account_id))
          .map((entry) => [entry.account_id, entry.unread_count] as const))
        let complete = true
        for (const account of enabledAccounts) {
          if (!byAccount.has(account.id)) {
            byAccount.set(account.id, null)
            complete = false
          }
        }
        return {
          totalUnread: complete ? response.total_unread : null,
          byAccount,
        }
      } catch (globalError) {
        const byAccount = new Map<string, number | null>()
        let total = 0
        let failed = false
        let succeeded = 0
        await Promise.all(enabledAccounts.map(async (account) => {
          const isFaulty = (account.sync_enabled === false || account.sync_status === 'failed' || account.sync_status === 'auth_failed')
          try {
            const unread = await fetchAccountFolders(account.id, signal)
            if (unread === null) {
              if (!isFaulty) {
                failed = true
              }
              byAccount.set(account.id, null)
              return
            }
            byAccount.set(account.id, unread)
            total += unread
            succeeded += 1
          } catch {
            if (!isFaulty) {
              failed = true
            }
            byAccount.set(account.id, null)
          }
        }))
        if (enabledAccounts.length && !succeeded) throw globalError
        return { totalUnread: failed ? null : total, byAccount }
      }
    },
    enabled: accounts.length > 0,
  })
  useEffect(() => {
    if (!openMenuGroupId && !editingGroupId && !newGroupOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setOpenMenuGroupId(null)
      setEditingGroupId(null)
      setNewGroupOpen(false)
      requestAnimationFrame(() => {
        if (editingGroupId || openMenuGroupId) groupMenuTrigger.current?.focus()
        else newGroupTrigger.current?.focus()
      })
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [editingGroupId, newGroupOpen, openMenuGroupId])
  const unreadByAccount = statsQuery.data?.byAccount ?? new Map<string, number | null>()
  const allInboxUnread = statsQuery.data ? statsQuery.data.totalUnread : (statsQuery.isError ? null : 0)
  const memberships = new Map<string, string[]>()
  for (const group of groups) memberships.set(group.id, orderedMembers(accounts, group.id).map((account) => account.id))
  const masterIds = accounts.map((account) => account.id)
  const ungroupedIds = accounts.filter((account) => !account.group_id || !memberships.has(account.group_id)).map((account) => account.id)
  const layoutSnapshot = layoutQuery.data
  const layoutReady = Boolean(
    groupsQuery.isSuccess && accountsQuery.isSuccess && layoutSnapshot &&
    layoutSnapshot.group_ids.length === groups.length && layoutSnapshot.group_ids.every((id, index) => id === groups[index].id) &&
    layoutSnapshot.master_account_ids.length === masterIds.length && layoutSnapshot.master_account_ids.every((id, index) => id === masterIds[index]) &&
    layoutSnapshot.ungrouped_account_ids.length === ungroupedIds.length && layoutSnapshot.ungrouped_account_ids.every((id, index) => id === ungroupedIds[index]) &&
    Object.keys(layoutSnapshot.group_account_ids).length === memberships.size &&
    [...memberships].every(([groupId, memberIds]) => {
      const snapshotMembers = layoutSnapshot.group_account_ids[groupId]
      return snapshotMembers?.length === memberIds.length && snapshotMembers.every((id, index) => id === memberIds[index])
    }),
  )

  async function invalidateOrganization() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.groups }),
      queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sidebarLayout }),
      queryClient.invalidateQueries({ queryKey: ['mail-core'] }),
    ])
  }

  async function saveLayout(layout: SidebarLayout) {
    if (layoutSaveInFlight.current) return
    if (!layoutReady || !layoutSnapshot) {
      setActionError('侧栏数据正在同步，请稍后重试')
      return
    }
    const membershipChanged = !sameMembership(currentLayout(), layout)
    layoutSaveInFlight.current = true
    setSavingLayout(true)
    setActionError('')
    try {
      await api.saveSidebarLayout({
        expected_revision: layoutSnapshot.revision,
        group_ids: layout.groupIds,
        master_account_ids: layout.masterIds,
        ungrouped_account_ids: layout.ungroupedIds,
        group_account_ids: layout.groupAccountIds,
      })
      if (membershipChanged) {
        useMailStore.setState((state) => ({ ...state, selectedKey: null, selectedIds: [] }))
        await resetGroupMailQueries()
      }
      await invalidateOrganization()
    } catch (error) {
      const status = error && typeof error === 'object' && 'status' in error ? (error as { status?: number }).status : undefined
      if (status === 409) {
        await invalidateOrganization()
        setActionError('侧栏已在其他窗口更新，数据已刷新；请重新操作')
      } else {
        setActionError(errorMessage(error, '保存侧栏顺序失败'))
      }
    } finally {
      layoutSaveInFlight.current = false
      setSavingLayout(false)
    }
  }

  function currentLayout(): SidebarLayout {
    return {
      groupIds: groups.map((group) => group.id),
      masterIds: masterIds.slice(),
      ungroupedIds: ungroupedIds.slice(),
      groupAccountIds: Object.fromEntries(memberships),
    }
  }

  async function createGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const name = newGroupName.trim()
    if (!name) return
    try {
      await api.createGroup({ name })
      setNewGroupName('')
      setNewGroupOpen(false)
      requestAnimationFrame(() => newGroupTrigger.current?.focus())
      await invalidateOrganization()
    } catch (error) {
      setActionError(errorMessage(error, '创建分组失败'))
    }
  }

  function cancelNewGroup() {
    setNewGroupOpen(false)
    setNewGroupName('')
    requestAnimationFrame(() => newGroupTrigger.current?.focus())
  }

  async function renameGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editingGroupId || renameSaveInFlight.current) return
    const name = editingGroupName.trim()
    if (!name) return
    renameSaveInFlight.current = true
    setSavingRename(true)
    try {
      const updated = await api.renameGroup(editingGroupId, name)
      if (view.type === 'group' && view.groupId === updated.id) {
        setView({ ...view, groupName: updated.name })
      }
      setEditingGroupId(null)
      setOpenMenuGroupId(null)
      requestAnimationFrame(() => groupMenuTrigger.current?.focus())
      await invalidateOrganization()
    } catch (error) {
      setActionError(errorMessage(error, '重命名分组失败'))
    } finally {
      renameSaveInFlight.current = false
      setSavingRename(false)
    }
  }

  async function deleteGroup(groupId: string, groupName: string) {
    if (!confirmAction(`删除分组“${groupName}”？账号和邮件会保留，并从该分组移出。`)) return
    try {
      await api.deleteGroup(groupId)
      if (view.type === 'group' && view.groupId === groupId) {
        setView({ type: 'allInbox' })
        setListFilter('all')
      }
      useMailStore.setState((state) => ({
        expandedSidebarGroups: state.expandedSidebarGroups.filter((id) => id !== groupId),
        expandedSidebarCategories: state.expandedSidebarCategories.filter((key) => !key.startsWith(`group:${groupId}:`)),
      }))
      setOpenGroupSearchIds((current) => current.filter((id) => id !== groupId))
      setGroupSearchTerms((current) => {
        if (!(groupId in current)) return current
        const next = { ...current }
        delete next[groupId]
        return next
      })
      setOpenMenuGroupId(null)
      await invalidateOrganization()
    } catch (error) {
      setActionError(errorMessage(error, '删除分组失败'))
    }
  }

  async function resetOrder() {
    if (layoutSaveInFlight.current) return
    if (!layoutReady || !layoutSnapshot) {
      setActionError('侧栏数据正在同步，请稍后重试')
      return
    }
    layoutSaveInFlight.current = true
    setSavingLayout(true)
    try {
      await api.resetSidebarAccountOrder(layoutSnapshot.revision)
      await invalidateOrganization()
      setActionError('')
    } catch (error) {
      const status = error && typeof error === 'object' && 'status' in error ? (error as { status?: number }).status : undefined
      if (status === 409) {
        await invalidateOrganization()
        setActionError('侧栏已在其他窗口更新，数据已刷新；请重新操作')
      } else {
        setActionError(errorMessage(error, '恢复默认排序失败'))
      }
    } finally {
      layoutSaveInFlight.current = false
      setSavingLayout(false)
    }
  }

  function selectGlobalCategory(category: FavoriteCategory) {
    if (category === 'inbox') setView({ type: 'allInbox' })
    else setView({ type: 'favorite', category })
    setListFilter(category === 'unread' ? 'unread' : 'all')
  }

  function selectGroupCategory(groupId: string, groupName: string, category: FavoriteCategory) {
    setView({ type: 'group', groupId, groupName, category })
    setListFilter(category === 'unread' ? 'unread' : 'all')
  }

  function closeGroupSearch(groupId: string) {
    setOpenGroupSearchIds((current) => current.filter((id) => id !== groupId))
    setGroupSearchTerms((current) => {
      if (!(groupId in current)) return current
      const next = { ...current }
      delete next[groupId]
      return next
    })
    requestAnimationFrame(() => {
      const trigger = [...document.querySelectorAll<HTMLButtonElement>('[data-search-toggle-group-id]')]
        .find((element) => element.dataset.searchToggleGroupId === groupId)
      trigger?.focus()
    })
  }

  function toggleGroupSearch(groupId: string) {
    if (openGroupSearchIds.includes(groupId)) {
      closeGroupSearch(groupId)
      return
    }
    setOpenGroupSearchIds((current) => current.includes(groupId) ? current : [...current, groupId])
  }

  function closeMasterSearch() {
    setMasterSearchOpen(false)
    setMasterSearchTerm('')
    requestAnimationFrame(() => masterSearchTriggerRef.current?.focus())
  }

  function toggleMasterSearch() {
    if (masterSearchOpen) {
      closeMasterSearch()
      return
    }
    setMasterSearchOpen(true)
  }

  function beginAccountDrag(event: DragEvent<HTMLDivElement>, accountId: string, groupId: string | null, sourceList: 'master' | 'group') {
    event.stopPropagation()
    if (!layoutReady || layoutSaveInFlight.current) {
      event.preventDefault()
      return
    }
    if ((event.target as HTMLElement).closest('[data-no-drag="true"]')) {
      event.preventDefault()
      return
    }
    dragPayload.current = { type: 'account', accountId, sourceGroupId: groupId, sourceList }
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', JSON.stringify(dragPayload.current))
  }

  function clearDropState() {
    dragPayload.current = null
    document.querySelectorAll('.tree-drop-target').forEach((element) => element.classList.remove('tree-drop-target'))
  }

  function suppressDragDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    event.stopPropagation()
    clearDropState()
  }

  function eventMatchesDrag(event: DragEvent<HTMLDivElement>): boolean {
    const current = dragPayload.current
    if (!current) return false
    try {
      const incoming = JSON.parse(event.dataTransfer.getData('text/plain')) as DragPayload
      return JSON.stringify(incoming) === JSON.stringify(current)
    } catch {
      return false
    }
  }

  function allowDrop(event: DragEvent<HTMLDivElement>) {
    if (!layoutReady || !dragPayload.current) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    event.currentTarget.classList.add('tree-drop-target')
  }

  function makeLayoutWithAccountMove(payload: Extract<DragPayload, { type: 'account' }>, targetGroupId: string | null, targetAccountId?: string, targetList: 'master' | 'group' = 'group'): SidebarLayout | null {
    if (targetAccountId === payload.accountId) return null
    const layout = currentLayout()
    if (targetList === 'master') {
      if (payload.sourceList === 'master') {
        if (!targetAccountId) return null
        layout.masterIds = moveBefore(layout.masterIds, payload.accountId, targetAccountId)
        return layout
      }
      if (!payload.sourceGroupId) return null
      layout.groupAccountIds[payload.sourceGroupId] = (layout.groupAccountIds[payload.sourceGroupId] || []).filter((id) => id !== payload.accountId)
      layout.ungroupedIds = moveBefore(layout.ungroupedIds, payload.accountId, targetAccountId)
      layout.masterIds = moveBefore(layout.masterIds, payload.accountId, targetAccountId)
      return layout
    }
    if (!targetGroupId) return null
    const targetMembers = layout.groupAccountIds[targetGroupId]
    if (!targetMembers) return null
    if (payload.sourceGroupId) {
      layout.groupAccountIds[payload.sourceGroupId] = (layout.groupAccountIds[payload.sourceGroupId] || []).filter((id) => id !== payload.accountId)
    } else {
      layout.ungroupedIds = layout.ungroupedIds.filter((id) => id !== payload.accountId)
    }
    layout.groupAccountIds[targetGroupId] = moveBefore(targetMembers.filter((id) => id !== payload.accountId), payload.accountId, targetAccountId)
    return layout
  }

  async function dropAccountOn(event: DragEvent<HTMLDivElement>, targetGroupId: string | null, targetAccountId?: string, targetList: 'master' | 'group' = 'group') {
    event.preventDefault()
    event.stopPropagation()
    const validDrag = eventMatchesDrag(event)
    const payload = dragPayload.current
    clearDropState()
    if (!validDrag || !payload || payload.type !== 'account') return
    const layout = makeLayoutWithAccountMove(payload, targetGroupId, targetAccountId, targetList)
    if (layout) await saveLayout(layout)
  }

  async function dropGroupOn(event: DragEvent<HTMLDivElement>, targetGroupId: string) {
    event.preventDefault()
    event.stopPropagation()
    const validDrag = eventMatchesDrag(event)
    const payload = dragPayload.current
    clearDropState()
    if (!validDrag || !payload || payload.type !== 'group' || payload.groupId === targetGroupId) return
    const layout = currentLayout()
    layout.groupIds = moveBefore(layout.groupIds, payload.groupId, targetGroupId)
    await saveLayout(layout)
  }

  function onDragEnd() {
    clearDropState()
    void queryClient.invalidateQueries({ queryKey: queryKeys.accounts })
  }

  async function onDropListHeader(event: DragEvent<HTMLDivElement>) {
    if (masterSearchActive) {
      suppressDragDrop(event)
      return
    }
    if (!eventMatchesDrag(event)) {
      event.preventDefault()
      clearDropState()
      return
    }
    const payload = dragPayload.current
    if (!payload || payload.type !== 'account' || !payload.sourceGroupId) {
      event.preventDefault()
      clearDropState()
      return
    }
    await dropAccountOn(event, null, undefined, 'master')
  }

  function renderCategory(category: FavoriteCategory, label: string, Icon: typeof Inbox, scope: { type: 'all' } | { type: 'group'; id: string; name: string }) {
    const key = scope.type === 'all' ? `all:${category}` : `group:${scope.id}:${category}`
    const expanded = expandedCategories.includes(key)
    const active = scope.type === 'all'
      ? ((category === 'inbox' && view.type === 'allInbox' && listFilter === 'all') || (view.type === 'favorite' && !view.accountId && view.category === category))
      : view.type === 'group' && view.groupId === scope.id && view.category === category
    const availableAccounts = scope.type === 'all'
      ? visibleAccounts
      : orderedMembers(accounts, scope.id).filter((account) => account.sync_enabled !== false)
    const groupSearchTerm = scope.type === 'group' ? groupSearchTerms[scope.id] || '' : ''
    const categoryAccounts = scope.type === 'group' && groupSearchTerm.trim()
      ? availableAccounts.filter((account) => matchesAccountSearch(account, groupSearchTerm))
      : availableAccounts
    return (
      <div key={key} className="tree-category-block">
        <div className={`tree-category-heading ${active ? 'active' : ''}`} style={{ paddingLeft: '24px' }}>
          <button type="button" className="tree-disclosure" aria-label={expanded ? `折叠 ${label}` : `展开 ${label}`} aria-expanded={expanded} onClick={() => toggleExpandedCategory(key)}>{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>
          <button data-ui={scope.type === 'all' ? 'SB13' : 'SB15'} type="button" className="tree-nav-row tree-category-row" aria-label={label} onClick={() => scope.type === 'all' ? selectGlobalCategory(category) : selectGroupCategory(scope.id, scope.name, category)}>
            <Icon size={16} aria-hidden="true" />
            <span className="tree-label">{label}</span>
            {scope.type === 'all' && category === 'inbox' && allInboxUnread !== null && allInboxUnread > 0 ? <span className="side-count unread-badge">{allInboxUnread}</span> : null}
            {scope.type === 'all' && category === 'inbox' && allInboxUnread === null ? <span className="side-count unread-badge unread-badge-unknown">-</span> : null}
          </button>
        </div>
        {expanded && <div className="tree-category-accounts">{categoryAccounts.map((account) => {
          const unread = unreadByAccount.get(account.id) ?? (statsQuery.data || statsQuery.isError ? null : undefined)
          const activeAccount = view.type === 'favorite' && view.category === category && view.accountId === account.id
          return <div key={account.id} className="tree-category-account-row">
            <button type="button" className={`tree-nav-row tree-category-account ${activeAccount ? 'active' : ''}`} style={{ paddingLeft: '48px' }} title={account.email} onClick={() => {
              setView({ type: 'favorite', category, accountId: account.id, email: account.email })
              setListFilter(category === 'unread' ? 'unread' : 'all')
            }}>
              <span className="tree-disclosure-slot" aria-hidden="true" />
              <AccountIcon email={account.email} provider={account.provider} accountType={account.account_type} groupColor={account.group_color} />
              <span className="tree-label">{account.email}</span>
              {(category === 'inbox' || category === 'unread') && unread === null ? <span className="side-count unread-badge unread-badge-unknown">-</span> : (category === 'inbox' || category === 'unread') && unread && unread > 0 ? <span className="side-count unread-badge">{unread}</span> : null}
            </button>
            <CopyAddress variant="icon" address={account.email} />
          </div>
        })}</div>}
      </div>
    )
  }

  function renderAccount(account: (typeof accounts)[number], sourceList: 'master' | 'group', ownerGroupId: string | null, depth: number, dragDisabled = false) {
    const expanded = expandedAccounts.includes(account.id)
    const unread = unreadByAccount.get(account.id) ?? (statsQuery.data || statsQuery.isError ? null : undefined)
    const selected = view.type === 'account' && view.accountId === account.id
    const targetContext = sourceList === 'master' ? 'master' : `group:${ownerGroupId}`
    return (
      <div
        key={`${targetContext}-${account.id}`}
        className="tree-account-block"
        draggable={!dragDisabled && !savingLayout && layoutReady}
        data-account-id={account.id}
        data-drop-list={targetContext}
        data-ui="SB10"
        onDragStart={(event) => dragDisabled
          ? suppressDragDrop(event)
          : beginAccountDrag(event, account.id, sourceList === 'group' ? ownerGroupId : account.group_id || null, sourceList)}
        onDragEnd={onDragEnd}
        onDragOver={(event) => dragDisabled ? suppressDragDrop(event) : allowDrop(event)}
        onDrop={(event) => dragDisabled
          ? suppressDragDrop(event)
          : void dropAccountOn(event, sourceList === 'group' ? ownerGroupId : null, account.id, sourceList)}
      >
        <div className={`tree-account-row ${selected ? 'active' : ''}`} style={{ paddingLeft: `${depth * 24}px` }}>
          <button
            data-no-drag="true"
            type="button"
            className="tree-disclosure"
            aria-label={expanded ? `折叠 ${account.email}` : `展开 ${account.email}`}
            aria-expanded={expanded}
            onClick={() => toggleExpandedAccount(account.id)}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
          <button type="button" className="tree-account-select" title={account.email} aria-expanded={expanded} onClick={() => toggleExpandedAccount(account.id)}>
            <AccountIcon email={account.email} provider={account.provider} accountType={account.account_type} groupColor={account.group_color} />
            <span className="tree-label">{account.email}</span>
            {(account.sync_status === 'failed' || account.sync_status === 'auth_failed') && <span className="tree-account-sync-error" role="img" aria-label="同步失败" title="同步失败"><AlertCircle size={14} /></span>}
            {unread === null ? <span className="side-count unread-badge unread-badge-unknown" aria-label="未读数未知">-</span> : unread && unread > 0 ? <span className="side-count unread-badge">{unread}</span> : null}
          </button>
          <CopyAddress variant="icon" address={account.email} />
        </div>
        {expanded && <AccountFolders accountId={account.id} accountEmail={account.email} unreadCount={unread} syncStatus={account.sync_status} />}
      </div>
    )
  }

  const groupSections = groups.map((group) => {
    const members = orderedMembers(accounts, group.id).filter((account) => account.sync_enabled !== false)
    const searchOpen = openGroupSearchIds.includes(group.id)
    const searchTerm = groupSearchTerms[group.id] || ''
    const searchActive = searchTerm.trim().length > 0
    const groupUnread = members.reduce<number | null>((total, account) => {
      const isFaulty = (account.sync_enabled === false || account.sync_status === 'failed' || account.sync_status === 'auth_failed')
      const count = unreadByAccount.get(account.id)
      if (count == null) {
        if (isFaulty) return total
        return null
      }
      if (total === null) return null
      return total + count
    }, 0)
    return (
      <SidebarGroupSection
        key={group.id}
        group={group}
        members={members}
        unreadCount={groupUnread}
        layoutReady={layoutReady}
        savingLayout={savingLayout}
        savingRename={savingRename}
        collapsed={!expandedGroups.includes(group.id) && !searchOpen}
        searchOpen={searchOpen}
        searchTerm={searchTerm}
        searchActive={searchActive}
        onToggleSearch={() => toggleGroupSearch(group.id)}
        onSearchTermChange={(value) => setGroupSearchTerms((current) => ({ ...current, [group.id]: value }))}
        onCloseSearch={() => closeGroupSearch(group.id)}
        active={view.type === 'group' && view.groupId === group.id}
        menuOpen={openMenuGroupId === group.id}
        editing={editingGroupId === group.id}
        editingName={editingGroupName}
        onToggle={() => toggleExpandedGroup(group.id)}
        onOpenMenu={(button) => {
          groupMenuTrigger.current = button
          setOpenMenuGroupId(openMenuGroupId === group.id ? null : group.id)
        }}
        onRenameStart={() => { setEditingGroupId(group.id); setEditingGroupName(group.name); setOpenMenuGroupId(null) }}
        onRenameName={setEditingGroupName}
        onRenameSubmit={renameGroup}
        onRenameCancel={() => { setEditingGroupId(null); requestAnimationFrame(() => groupMenuTrigger.current?.focus()) }}
        onDelete={() => void deleteGroup(group.id, group.name)}
        onDragEnd={clearDropState}
        renderCategory={(category, label, Icon) => renderCategory(category, label, Icon, { type: 'group', id: group.id, name: group.name })}
        onDragStart={(event) => {
          if (searchActive) {
            event.preventDefault()
            event.stopPropagation()
            return
          }
          if (!layoutReady || layoutSaveInFlight.current) {
            event.preventDefault()
            return
          }
          if ((event.target as HTMLElement).closest('[data-no-drag="true"]')) {
            event.preventDefault()
            return
          }
          event.stopPropagation()
          dragPayload.current = { type: 'group', groupId: group.id }
          event.dataTransfer.effectAllowed = 'move'
          event.dataTransfer.setData('text/plain', JSON.stringify(dragPayload.current))
        }}
        onDragOver={(event) => searchActive ? suppressDragDrop(event) : allowDrop(event)}
        onDrop={(event) => {
          if (searchActive) {
            suppressDragDrop(event)
            return
          }
          if (dragPayload.current?.type === 'group') void dropGroupOn(event, group.id)
          else void dropAccountOn(event, group.id)
        }}
        renderAccount={(account) => renderAccount(account, 'group', group.id, 1, searchActive)}
      />
    )
  })

  return (
    <aside
      ref={sidebarRef}
      className="sidebar"
      aria-label="邮箱导航"
      role={drawerOpen ? 'dialog' : undefined}
      aria-modal={drawerOpen ? true : undefined}
      tabIndex={drawerOpen ? -1 : undefined}
    >
      <div className="sidebar-scroll tree-sidebar-scroll">
        {actionError && <div className="tree-action-error" role="alert"><AlertCircle size={14} /><span>{actionError}</span><button type="button" aria-label="关闭错误提示" onClick={() => setActionError('')}><X size={14} /></button></div>}
        <section className="tree-section">
          <div className="tree-section-heading">
            <button
              type="button"
              className="tree-disclosure"
              aria-label={sidebarSections.allAccounts ? '折叠' : '展开'}
              aria-expanded={sidebarSections.allAccounts}
              onClick={() => toggleSidebarSection('allAccounts')}
            >
              {sidebarSections.allAccounts ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <button
              data-ui="SB12"
              type="button"
              className="tree-heading-main"
              aria-expanded={sidebarSections.allAccounts}
              onClick={() => toggleSidebarSection('allAccounts')}
            >
              <MailOpen size={16} aria-hidden="true" />
              <span className="tree-label">所有账号</span>
            </button>
          </div>
          {sidebarSections.allAccounts && <div>{CATEGORY_ITEMS.map(({ category, label, icon: Icon }) => renderCategory(category, label, Icon, { type: 'all' }))}</div>}
        </section>

        <section className="tree-section tree-groups-section" aria-label="邮箱分组">
          {groupSections}
          {newGroupOpen && <form className="tree-inline-form" onSubmit={(event) => void createGroup(event)}>
            <input autoFocus aria-label="新分组名称" value={newGroupName} maxLength={128} onChange={(event) => setNewGroupName(event.target.value)} placeholder="新分组名称" />
            <button type="submit" aria-label="创建分组"><Plus size={16} /></button>
            <button type="button" aria-label="取消创建" onClick={cancelNewGroup}><X size={15} /></button>
          </form>}
        </section>

        <section className="tree-section">
          <div
            className="tree-section-heading tree-drop-zone"
            data-ui="SB16"
            data-drop-kind="master-list"
            onDragOver={(event) => masterSearchActive ? suppressDragDrop(event) : allowDrop(event)}
            onDrop={(event) => void onDropListHeader(event)}
          >
            <button
              type="button"
              className="tree-disclosure"
              aria-label={masterSectionExpanded ? '折叠' : '展开'}
              aria-expanded={masterSectionExpanded}
              onClick={() => toggleSidebarSection('accountList')}
            >
              {masterSectionExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <button type="button" className="tree-heading-main" aria-expanded={masterSectionExpanded} onClick={() => toggleSidebarSection('accountList')}>
              <FolderIcon size={16} aria-hidden="true" /><span className="tree-label">账号列表</span>
            </button>
            <button ref={masterSearchTriggerRef} type="button" className="tree-icon-action" aria-label={masterSearchOpen ? '关闭账号列表搜索' : '搜索账号列表'} aria-expanded={masterSearchOpen} title={masterSearchOpen ? '关闭搜索' : '搜索账号'} onClick={toggleMasterSearch}><Search size={15} /></button>
            <button ref={newGroupTrigger} type="button" className="tree-icon-action" aria-label="新建分组" title="新建分组" onClick={() => { setNewGroupOpen(true); setActionError('') }}><FolderPlus size={16} /></button>
            <button type="button" className="tree-icon-action" aria-label="恢复默认排序" title="恢复默认排序" onClick={() => void resetOrder()}><ArrowDownWideNarrow size={16} /></button>
          </div>
          {masterSectionExpanded && <div className="tree-account-list" data-search-active={masterSearchActive} onDragOver={(event) => masterSearchActive ? suppressDragDrop(event) : allowDrop(event)} onDrop={(event) => masterSearchActive ? suppressDragDrop(event) : void onDropListHeader(event)}>
            {masterSearchOpen && <div className="tree-account-search" data-no-drag="true">
              <Search size={14} aria-hidden="true" />
              <input
                ref={masterSearchInputRef}
                aria-label="搜索账号列表"
                type="search"
                value={masterSearchTerm}
                placeholder="搜索邮箱或名称"
                onChange={(event) => setMasterSearchTerm(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Escape') return
                  event.preventDefault()
                  event.stopPropagation()
                  closeMasterSearch()
                }}
              />
              {masterSearchTerm && <button type="button" aria-label="清除账号列表搜索" title="清除搜索" onClick={() => {
                setMasterSearchTerm('')
                requestAnimationFrame(() => masterSearchInputRef.current?.focus())
              }}><X size={14} /></button>}
            </div>}
            {(groupsQuery.isLoading || accountsQuery.isLoading || layoutQuery.isLoading) && <div className="tree-loading" style={{ paddingLeft: '24px' }}>正在加载账户…</div>}
            {(groupsQuery.error || accountsQuery.error || layoutQuery.error) && <div className="tree-load-error" role="alert" style={{ paddingLeft: '24px' }}><span>{errorMessage(accountsQuery.error || groupsQuery.error || layoutQuery.error, '账户加载失败')}</span><button className="tree-retry" type="button" onClick={() => { void groupsQuery.refetch(); void accountsQuery.refetch(); void layoutQuery.refetch() }}>重试</button></div>}
            {statsQuery.error && <div className="tree-folder-status" role="status" style={{ paddingLeft: '24px' }}>未读统计暂不可用：{errorMessage(statsQuery.error, '统计加载失败')} <button className="tree-retry" type="button" onClick={() => void statsQuery.refetch()}>重试统计</button></div>}
            {masterSearchActive && filteredMasterAccounts.length === 0 && <div className="tree-no-search-results">未找到匹配账号</div>}
            {filteredMasterAccounts.map((account) => renderAccount(account, 'master', account.group_id || null, 1, masterSearchActive))}
          </div>}
        </section>
      </div>
      <div className="sidebar-footer">
        <button data-ui="SB11" className="footer-btn" onClick={() => { closeMobileSidebar(); openSettings() }}><Settings size={17} /><span>设置</span></button>
      </div>
    </aside>
  )
}

interface SidebarGroupSectionProps {
  group: GroupItem
  members: AccountSummary[]
  unreadCount: number | null
  layoutReady: boolean
  savingLayout: boolean
  savingRename: boolean
  collapsed: boolean
  searchOpen: boolean
  searchTerm: string
  searchActive: boolean
  onToggleSearch: () => void
  onSearchTermChange: (value: string) => void
  onCloseSearch: () => void
  active: boolean
  menuOpen: boolean
  editing: boolean
  editingName: string
  onToggle: () => void
  onOpenMenu: (button: HTMLButtonElement) => void
  onRenameStart: () => void
  onRenameName: (name: string) => void
  onRenameSubmit: (event: FormEvent<HTMLFormElement>) => void
  onRenameCancel: () => void
  onDelete: () => void
  onDragEnd: () => void
  renderCategory: (category: FavoriteCategory, label: string, Icon: typeof Inbox) => React.ReactNode
  onDragStart: (event: DragEvent<HTMLDivElement>) => void
  onDragOver: (event: DragEvent<HTMLDivElement>) => void
  onDrop: (event: DragEvent<HTMLDivElement>) => void
  renderAccount: (account: AccountSummary) => React.ReactNode
}

function SidebarGroupSection(props: SidebarGroupSectionProps) {
  const unread = props.unreadCount
  const visibleMembers = props.searchActive
    ? props.members.filter((account) => matchesAccountSearch(account, props.searchTerm))
    : props.members
  function suppressDragDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.classList.remove('tree-drop-target')
  }
  const menus = props.menuOpen && <div className="tree-group-menu" role="menu">
    <button type="button" role="menuitem" onClick={props.onRenameStart}><Pencil size={14} />重命名分组</button>
    <button type="button" role="menuitem" className="danger" onClick={props.onDelete}><Trash2 size={14} />删除分组</button>
  </div>
  return (
    <div className="tree-group-block" data-group-id={props.group.id} onDragOver={(event) => props.searchActive ? suppressDragDrop(event) : props.onDragOver(event)} onDrop={(event) => props.searchActive ? suppressDragDrop(event) : props.onDrop(event)}>
      <div className={`tree-group-heading ${props.active ? 'active' : ''}`} draggable={!props.searchActive && !props.editing && !props.savingLayout && props.layoutReady} onDragStart={(event) => props.searchActive ? suppressDragDrop(event) : props.onDragStart(event)} onDragEnd={props.onDragEnd}>
        <button type="button" data-no-drag="true" className="tree-disclosure" aria-label={props.collapsed ? `展开分组 ${props.group.name}` : `折叠分组 ${props.group.name}`} aria-expanded={!props.collapsed} onClick={props.onToggle}>{props.collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}</button>
        <button type="button" className="tree-group-select" onClick={props.onToggle}><FolderIcon size={16} /><span className="tree-label">{props.group.name}</span><span className="tree-count">{props.members.length}</span>{unread === null ? <span className="side-count unread-badge unread-badge-unknown">-</span> : unread > 0 ? <span className="side-count unread-badge">{unread}</span> : null}</button>
        <button type="button" data-search-toggle-group-id={props.group.id} data-no-drag="true" className="tree-icon-action" aria-label={props.searchOpen ? `关闭分组搜索 ${props.group.name}` : `搜索分组 ${props.group.name}`} aria-expanded={props.searchOpen} title={props.searchOpen ? '关闭搜索' : '搜索账号'} onClick={props.onToggleSearch}><Search size={15} /></button>
        <button type="button" data-no-drag="true" className="tree-icon-action" aria-label={`分组操作 ${props.group.name}`} aria-expanded={props.menuOpen} onClick={(event) => props.onOpenMenu(event.currentTarget)}><MoreHorizontal size={16} /></button>
        {menus}
      </div>
      {props.editing && <form className="tree-inline-form" onSubmit={props.onRenameSubmit}><input autoFocus aria-label="重命名分组" maxLength={128} value={props.editingName} disabled={props.savingRename} onChange={(event) => props.onRenameName(event.target.value)} /><button type="submit" aria-label="保存分组名称" disabled={props.savingRename}><CheckIcon size={15} /></button><button type="button" aria-label="取消重命名" disabled={props.savingRename} onClick={props.onRenameCancel}><X size={15} /></button></form>}
      {props.searchOpen && <div className="tree-account-search" data-no-drag="true">
        <Search size={14} aria-hidden="true" />
        <input
          data-search-group-id={props.group.id}
          aria-label={`搜索分组账号：${props.group.name}`}
          type="search"
          value={props.searchTerm}
          placeholder="搜索邮箱或名称"
          onChange={(event) => props.onSearchTermChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            event.preventDefault()
            event.stopPropagation()
            props.onCloseSearch()
          }}
        />
        {props.searchTerm && <button type="button" aria-label={`清除分组搜索 ${props.group.name}`} title="清除搜索" onClick={(event) => {
          const input = event.currentTarget.parentElement?.querySelector('input')
          props.onSearchTermChange('')
          requestAnimationFrame(() => input?.focus())
        }}><X size={14} /></button>}
      </div>}
      {!props.collapsed && <div className="tree-group-children">
        {CATEGORY_ITEMS.map(({ category, label, icon: Icon }) => props.renderCategory(category, label, Icon))}
        {props.searchActive && visibleMembers.length === 0 && <div className="tree-no-search-results">未找到匹配账号</div>}
        {visibleMembers.map(props.renderAccount)}
      </div>}
    </div>
  )
}

export default memo(Sidebar)
