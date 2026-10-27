import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Folder, Inbox, LoaderCircle, Monitor, Moon, PanelLeft, Pencil, Plus, RefreshCw, Search, Settings as SettingsIcon, Sun, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type Ref } from 'react'
import { api, type AccountSummary } from '../api/client'
import { fetchAccounts, fetchGroups, queryKeys, resetGroupMailQueries, resetMailListQueries } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { formatShortcut, getDefaultShortcut } from '../lib/ui_shortcut'
import { confirmAction, errorMessage } from '../lib/actions'
import { useIsWide } from '../lib/viewport'
import AccountIcon from './AccountIcon'
import CopyAddress from './CopyAddress'
import AccountDialog from './settings_account_form'

type Section = 'accounts' | 'groups' | 'general'
type Scope = Section | 'password'
const BATCH_CONCURRENCY = 4
type Feedback = { message: string; error?: boolean }
const providers: Record<string, string> = { imap: 'IMAP', graph: 'Microsoft Graph' }
const syncStates: Record<string, string> = { idle: '空闲', running: '同步中', failed: '同步失败', auth_failed: '认证失败', pending: '等待同步' }
const syncFailed = (account: AccountSummary) => ['failed', 'auth_failed'].includes(account.sync_status)
const accountDomain = (email: string) => email.slice(email.lastIndexOf('@') + 1).trim().toLowerCase()

function Status({ value }: { value?: Feedback }) {
  if (!value) return null
  return <div className={`settings-feedback${value.error ? ' is-error' : ''}`} role={value.error ? 'alert' : 'status'}>{value.message}</div>
}

/** Settings occupies the workspace after the mail sidebar. */
export default function SettingsPage({
  sidebarToggleRef,
  oauthReturn = false,
  onOAuthReturnConsumed,
}: {
  sidebarToggleRef?: Ref<HTMLButtonElement>
  oauthReturn?: boolean
  onOAuthReturnConsumed?: () => void
} = {}) {
  const theme = useMailStore(s => s.theme)
  const setTheme = useMailStore(s => s.setTheme)
  const accountIconMode = useMailStore(s => s.accountIconMode)
  const setAccountIconMode = useMailStore(s => s.setAccountIconMode)
  const uiReferenceEnabled = useMailStore(s => s.uiReferenceEnabled ?? true)
  const setUiReferenceEnabled = useMailStore(s => s.setUiReferenceEnabled)
  const uiReferenceShortcut = useMailStore(s => s.uiReferenceShortcut)
  const setUiReferenceShortcut = useMailStore(s => s.setUiReferenceShortcut)
  const closeSettings = useMailStore(s => s.closeSettings)
  const sidebarCollapsed = useMailStore(s => s.sidebarCollapsed)
  const toggleSidebar = useMailStore(s => s.toggleSidebar)
  const mobileSidebarOpen = useMailStore(s => s.mobileSidebarOpen)
  const toggleMobileSidebar = useMailStore(s => s.toggleMobileSidebar)
  const wide = useIsWide()
  const qc = useQueryClient()
  const accountsQuery = useQuery({ queryKey: queryKeys.accounts, queryFn: fetchAccounts })
  const groupsQuery = useQuery({ queryKey: queryKeys.groups, queryFn: fetchGroups })
  const settingsQuery = useQuery({ queryKey: queryKeys.settings, queryFn: async () => (await api.getSettings()).settings })
  const accounts = accountsQuery.data || []
  const groups = groupsQuery.data || []
  const [section, setSection] = useState<Section>('accounts')
  const [feedback, setFeedback] = useState<Partial<Record<Scope, Feedback>>>({})
  // Pending is tracked per scope (A125): a slow operation in one section
  // must not disable or silently swallow operations in the others.
  const [pendingScopes, setPendingScopes] = useState<Partial<Record<Scope, boolean>>>({})
  const pendingRef = useRef<Set<Scope>>(new Set())
  const pendingAccounts = !!pendingScopes.accounts
  const pendingGroups = !!pendingScopes.groups
  const pendingGeneral = !!pendingScopes.general
  const pendingPassword = !!pendingScopes.password
  const [addOpen, setAddOpen] = useState(false)
  const [editingAccount, setEditingAccount] = useState<AccountSummary | null>(null)
  const [search, setSearch] = useState('')
  const [groupFilter, setGroupFilter] = useState('all')
  const [stateFilter, setStateFilter] = useState('all')
  const [domainFilter, setDomainFilter] = useState('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkGroup, setBulkGroup] = useState('')
  const [groupSearch, setGroupSearch] = useState('')
  const [groupName, setGroupName] = useState('')
  const [editingGroup, setEditingGroup] = useState<string | null>(null)
  const [rename, setRename] = useState('')
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const selectAllRef = useRef<HTMLInputElement>(null)
  const groupInputRef = useRef<HTMLInputElement>(null)
  const saved = settingsQuery.data || {}
  const timezone = draft.app_timezone ?? saved.app_timezone ?? ''
  const timeoutSeconds = draft.mail_fetch_timeout_seconds ?? saved.mail_fetch_timeout_seconds ?? ''
  const query = search.trim().toLowerCase()
  const domains = [...new Set(accounts.map(account => accountDomain(account.email)).filter(Boolean))].sort((a, b) => a.localeCompare(b))
  const filtered = accounts.filter(a =>
    (!query || `${a.email} ${providers[a.provider] || a.provider} ${a.group_name || '未分组'} ${(a.recipient_addresses || []).join(' ')}`.toLowerCase().includes(query)) &&
    (groupFilter === 'all' || (groupFilter === 'ungrouped' ? !a.group_id : a.group_id === groupFilter)) &&
    (stateFilter === 'all' || (stateFilter === 'enabled' ? a.sync_enabled !== false : stateFilter === 'disabled' ? a.sync_enabled === false : syncFailed(a))) &&
    (domainFilter === 'all' || accountDomain(a.email) === domainFilter),
  )
  const selectedAccounts = accounts.filter(a => selected.has(a.id))
  const filteredSelected = filtered.filter(a => selected.has(a.id)).length
  const allSelected = filtered.length > 0 && filteredSelected === filtered.length
  const accountDialogOpen = addOpen || editingAccount !== null

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = filteredSelected > 0 && !allSelected
  }, [filteredSelected, allSelected])

  useEffect(() => {
    const hasOAuthReturn = oauthReturn || (typeof window !== 'undefined' && window.location.hash === '#oauth-return')
    if (!hasOAuthReturn || typeof api.getActiveOAuthFlow !== 'function' || accountsQuery.isPending) return
    const loadedAccounts = accountsQuery.data || []
    let cancelled = false
    void api.getActiveOAuthFlow().then(res => {
      if (cancelled || !res?.flow) return
      setSection('accounts')
      if (res.flow.intent === 'create') {
        setEditingAccount(null)
        setAddOpen(true)
      } else if (res.flow.account_id) {
        const target = loadedAccounts.find(a => a.id === res.flow?.account_id)
        if (target) {
          setAddOpen(false)
          setEditingAccount(target)
        }
      }
    }).catch(() => {}).finally(() => {
      if (cancelled) return
      if (typeof window !== 'undefined' && window.location.hash === '#oauth-return') {
        window.history?.replaceState?.(null, '', `${window.location.pathname}${window.location.search}`)
      }
      onOAuthReturnConsumed?.()
    })
    return () => { cancelled = true }
  }, [accountsQuery.isPending, accountsQuery.data, oauthReturn, onOAuthReturnConsumed])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !accountDialogOpen) closeSettings()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closeSettings, accountDialogOpen])

  function report(scope: Scope, message: string, error = false) {
    setFeedback(current => ({ ...current, [scope]: { message, error } }))
  }

  function setScopePending(scope: Scope, value: boolean) {
    if (value) pendingRef.current.add(scope)
    else pendingRef.current.delete(scope)
    setPendingScopes(current => ({ ...current, [scope]: value }))
  }

  async function run<T,>(scope: Scope, label: string, fn: () => Promise<T>, success: string | ((result: T) => string) = `${label}成功`) {
    if (pendingRef.current.has(scope)) return { ok: false as const }
    setScopePending(scope, true)
    report(scope, `${label}…`)
    try {
      const data = await fn()
      report(scope, typeof success === 'function' ? success(data) : success)
      return { ok: true as const, data }
    } catch (error) {
      report(scope, errorMessage(error, `${label}失败`), true)
      return { ok: false as const }
    } finally {
      setScopePending(scope, false)
    }
  }

  async function refreshOrganization() {
    // Statistics derive their account IDs from this cache; refresh membership first.
    await qc.invalidateQueries({ queryKey: queryKeys.accounts })
    await Promise.all([
      qc.invalidateQueries({ queryKey: queryKeys.groups }),
      qc.invalidateQueries({ queryKey: queryKeys.sidebarLayout }),
      qc.invalidateQueries({ queryKey: ['mail-core'], predicate: query => query.queryKey[1] !== 'stats' }),
    ])
    if (qc.getQueryData<AccountSummary[]>(queryKeys.accounts)?.length) {
      await qc.invalidateQueries({ queryKey: queryKeys.stats })
    }
  }

  async function moveAccount(account: AccountSummary, groupId: string) {
    await api.updateAccount(account.id, groupId ? { group_id: groupId } : { clear_group: true })
    if ((account.group_id ?? '') !== groupId) {
      useMailStore.setState({ selectedKey: null, selectedIds: [] })
      await resetGroupMailQueries()
    }
  }

  async function batch(action: 'move' | 'sync' | 'enable' | 'disable') {
    const labels = { move: '移动分组', sync: '同步账户', enable: '启用同步', disable: '暂停同步' }
    const targets = selectedAccounts
    const result = await run('accounts', labels[action], async () => {
      const failed: Array<{ id: string; message: string }> = []
      // Concurrency pool with per-item progress (A125): one slow account no
      // longer serializes the whole batch, and progress is reported as items
      // settle instead of only at the end.
      let completed = 0
      let nextIndex = 0
      async function worker() {
        while (nextIndex < targets.length) {
          const account = targets[nextIndex]
          nextIndex += 1
          try {
            if (action === 'move') await moveAccount(account, bulkGroup)
            else if (action === 'sync') await api.syncAccount(account.id)
            else await api.updateAccount(account.id, { sync_enabled: action === 'enable' })
          } catch (error) {
            failed.push({ id: account.id, message: `${account.email}：${errorMessage(error)}` })
          } finally {
            completed += 1
            if (targets.length > 1) report('accounts', `${labels[action]}中 ${completed}/${targets.length}…`)
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(BATCH_CONCURRENCY, targets.length) }, () => worker()))
      setSelected(new Set(failed.map(item => item.id)))
      await refreshOrganization()
      return { failed, count: targets.length }
    }, data => `${data.count - data.failed.length} 个成功，${data.failed.length} 个失败`)
    if (result.ok && result.data.failed.length) {
      report('accounts', `${result.data.count - result.data.failed.length} 个成功，${result.data.failed.length} 个失败\n${result.data.failed.map(item => item.message).join('\n')}`, true)
    }
  }

  async function deleteAccount(account: AccountSummary) {
    if (!confirmAction(`删除账户 ${account.email}？此操作会删除本地关联邮件，不会删除邮箱服务商上的邮件。`)) return
    await run('accounts', '删除账户', async () => {
      await api.deleteAccount(account.id)
      await qc.invalidateQueries({ queryKey: queryKeys.accounts })
      setSelected(current => new Set([...current].filter(id => id !== account.id)))
      const state = useMailStore.getState()
      if ('accountId' in state.view && state.view.accountId === account.id) {
        useMailStore.setState({ view: { type: 'allInbox' }, search: '', listFilter: 'all' })
      }
      useMailStore.setState({ selectedKey: null, selectedIds: [] })
      if (accounts.length === 1) qc.setQueryData(queryKeys.stats, { totalUnread: 0, byAccount: new Map<string, number | null>() })
      else await qc.resetQueries({ queryKey: queryKeys.stats })
      await resetMailListQueries()
      await refreshOrganization()
    }, '已删除')
  }

  // Sync-preference toggles stay silent on success (p054); only failures surface feedback.
  async function toggleSyncPreference(account: AccountSummary) {
    if (pendingRef.current.has('accounts')) return
    setScopePending('accounts', true)
    try {
      await api.updateAccount(account.id, { sync_enabled: account.sync_enabled === false })
      await refreshOrganization()
    } catch (error) {
      report('accounts', errorMessage(error, '更新同步偏好失败'), true)
    } finally {
      setScopePending('accounts', false)
    }
  }

  function showGroupAccounts(id: string) {
    setSearch('')
    setGroupFilter(id)
    setStateFilter('all')
    setDomainFilter('all')
    setSelected(new Set())
    setSection('accounts')
  }

  return (
    <section className="settings-page" aria-label="应用设置">
      <div className="settings-page-body">
        <nav data-ui="ST04" className="settings-nav" aria-label="设置分类">
          <div className="settings-nav-header">
            <button
              ref={sidebarToggleRef}
              data-ui="ST01"
              data-testid="sidebar-toggle"
              type="button"
              className="sidebar-expand-btn settings-icon-button"
              title={wide ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (mobileSidebarOpen ? '关闭导航' : '打开导航')}
              aria-label={wide ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (mobileSidebarOpen ? '关闭导航' : '打开导航')}
              aria-expanded={wide ? !sidebarCollapsed : mobileSidebarOpen}
              onClick={wide ? toggleSidebar : toggleMobileSidebar}
            >
              <PanelLeft size={18} />
            </button>
            <span className="settings-nav-title">设置</span>
          </div>
          <span className="settings-nav-caption">邮箱管理</span>
          <button data-ui="ST10" type="button" className="settings-nav-item" aria-current={section === 'accounts' ? 'page' : undefined} onClick={() => setSection('accounts')}><Inbox size={16} />账户管理</button>
          <button data-ui="ST11" type="button" className="settings-nav-item" aria-current={section === 'groups' ? 'page' : undefined} onClick={() => setSection('groups')}><Folder size={16} />分组管理</button>
          <span className="settings-nav-caption">应用</span>
          <button data-ui="ST12" type="button" className="settings-nav-item" aria-current={section === 'general' ? 'page' : undefined} onClick={() => setSection('general')}><SettingsIcon size={16} />通用</button>
        </nav>
        <div className={`settings-content settings-content-${section}`}>
          {section === 'accounts' && <>
            <div className="settings-section-head"><div><h1>账户管理</h1></div></div>
            {accountsQuery.isError && <div className="settings-feedback is-error" role="alert">加载账户失败：{errorMessage(accountsQuery.error)} <button type="button" className="settings-text-button" onClick={() => void accountsQuery.refetch()}>重试</button></div>}
            {groupsQuery.isError && <div className="settings-feedback is-error" role="alert">加载分组失败：{errorMessage(groupsQuery.error)} <button type="button" className="settings-text-button" onClick={() => void groupsQuery.refetch()}>重试</button></div>}
            <div className="settings-accounts-first-row">
              <div className="settings-summary"><span>账户总数 <strong>{accountsQuery.isPending ? '—' : accounts.length}</strong></span><span>已显示 <strong>{accountsQuery.isPending ? '—' : filtered.length}</strong></span><span>已同步 <strong>{accountsQuery.isPending ? '—' : accounts.filter(a => a.sync_enabled !== false).length}</strong></span><span>已暂停同步 <strong>{accountsQuery.isPending ? '—' : accounts.filter(a => a.sync_enabled === false).length}</strong></span></div>
              <div className="settings-accounts-actions">
                <button data-ui="ST14" type="button" className="settings-button is-primary" onClick={() => { setEditingAccount(null); setAddOpen(true) }} disabled={pendingAccounts}><Plus size={15} />添加账户</button>
                <button data-ui="ST15" type="button" className="settings-button" disabled={pendingAccounts || accountsQuery.isPending || accountsQuery.isError} onClick={() => void run('accounts', '全量同步', async () => { const result = await api.syncAll(); await qc.invalidateQueries({ queryKey: queryKeys.accounts }); return result }, result => `已排队 ${result.target_count ?? 0} 个全量同步任务`)}><RefreshCw size={14} />同步全部账户</button>
              </div>
              <div className="settings-toolbar">
                <label className="settings-search"><Search size={15} /><input type="search" aria-label="搜索账户" placeholder="搜索邮箱、域名、服务商或分组" value={search} onChange={event => setSearch(event.target.value)} /></label>
                <select aria-label="按分组筛选" value={groupFilter} onChange={event => setGroupFilter(event.target.value)} disabled={groupsQuery.isError}><option value="all">所有分组</option><option value="ungrouped">未分组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select>
                <select aria-label="按同步状态筛选" value={stateFilter} onChange={event => setStateFilter(event.target.value)}><option value="all">全部状态</option><option value="enabled">已启用同步</option><option value="disabled">已暂停同步</option><option value="failed">同步异常</option></select>
                <select aria-label="按邮箱域名筛选" value={domainFilter} onChange={event => setDomainFilter(event.target.value)}><option value="all">所有域名</option>{domains.map(domain => <option key={domain} value={domain}>{domain}</option>)}</select>
              </div>
            </div>
            {selectedAccounts.length > 0 && <div className="settings-bulk-bar" aria-label="批量账户操作">
              <strong>已选 {selectedAccounts.length} 个账户</strong><select aria-label="批量移动分组" value={bulkGroup} onChange={event => setBulkGroup(event.target.value)} disabled={pendingAccounts || groupsQuery.isError}><option value="">移至未分组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select>
              <button className="settings-button" type="button" disabled={pendingAccounts || groupsQuery.isError} onClick={() => void batch('move')}>移动分组</button>
              <button className="settings-button" type="button" disabled={pendingAccounts} onClick={() => void batch('sync')}>同步</button>
              <button className="settings-button" type="button" disabled={pendingAccounts} onClick={() => void batch('enable')}>启用同步</button>
              <button className="settings-button" type="button" disabled={pendingAccounts} onClick={() => void batch('disable')}>暂停同步</button>
              <button className="settings-text-button" type="button" disabled={pendingAccounts} onClick={() => setSelected(new Set())}>取消选择</button>
            </div>}
            <Status value={feedback.accounts} />
            <div className="settings-account-table" role="region" aria-label="账户列表" aria-busy={accountsQuery.isPending || pendingAccounts}>
              <div className="settings-account-head"><input ref={selectAllRef} type="checkbox" aria-label="选择当前筛选的全部账户" checked={allSelected} disabled={pendingAccounts || !filtered.length} onChange={event => setSelected(current => {
                const next = new Set(current)
                filtered.forEach(account => event.target.checked ? next.add(account.id) : next.delete(account.id))
                return next
              })} /><span>账户 · {filtered.length}</span><span>所属分组</span><span>同步状态</span><span>同步开关</span><span>操作</span></div>
              <div className="settings-account-rows">
                {accountsQuery.isPending ? <div className="settings-empty"><LoaderCircle size={20} className="settings-spin" />正在加载账户…</div> : filtered.map(account => <div className="settings-account-row" key={account.id}>
                  <input type="checkbox" aria-label={`选择 ${account.email}`} checked={selected.has(account.id)} disabled={pendingAccounts} onChange={event => setSelected(current => {
                    const next = new Set(current)
                    if (event.target.checked) next.add(account.id)
                    else next.delete(account.id)
                    return next
                  })} />
                  <div className="settings-account-identity"><AccountIcon email={account.email} provider={account.provider} accountType={account.account_type} groupColor={account.group_color} /><div><strong title={account.email}><CopyAddress address={account.email} className="settings-copy-email">{account.email}</CopyAddress></strong><small>{providers[account.provider] || account.provider}{account.group_name ? ` · ${account.group_name}` : ''}</small></div></div>
                  <select aria-label={`移动 ${account.email}`} value={account.group_id ?? ''} disabled={pendingAccounts || !groupsQuery.isSuccess} onChange={event => {
                    const groupId = event.target.value
                    void run('accounts', '移动账号', async () => { await moveAccount(account, groupId); await refreshOrganization() }, '账号分组已更新')
                  }}><option value="">不加入分组</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select>
                  <span className={`settings-sync-status${syncFailed(account) ? ' is-error' : ''}`}><i />{syncStates[account.sync_status] || account.sync_status || '状态未知'}</span>
                  <button className="settings-switch" type="button" role="switch" aria-checked={account.sync_enabled !== false} aria-label={`${account.sync_enabled === false ? '启用' : '暂停'}同步 ${account.email}`} disabled={pendingAccounts} onClick={() => void toggleSyncPreference(account)}><span /></button>
                  <div className="settings-row-actions"><button type="button" className="settings-icon-button" title="编辑账户" aria-label={`编辑账户 ${account.email}`} disabled={pendingAccounts} onClick={() => { setAddOpen(false); setEditingAccount(account) }}><Pencil size={14} /></button><button type="button" className="settings-icon-button" title="立即同步" aria-label={`同步 ${account.email}`} disabled={pendingAccounts || account.sync_enabled === false} onClick={() => void run('accounts', '同步', async () => { await api.syncAccount(account.id); await qc.invalidateQueries({ queryKey: queryKeys.accounts }) }, '已排队同步')}><RefreshCw size={14} /></button><button type="button" className="settings-icon-button is-danger" aria-label={`删除账户 ${account.email}`} title="删除账户" disabled={pendingAccounts} onClick={() => void deleteAccount(account)}><Trash2 size={14} /><span className="settings-sr-only">删除</span></button></div>
                </div>)}
                {!accountsQuery.isPending && !accountsQuery.isError && !filtered.length && <div className="settings-empty"><Inbox size={26} /><strong>{accounts.length ? '没有匹配的账户' : '还没有添加账户'}</strong><span>{accounts.length ? '调整搜索词或筛选条件。' : '添加邮箱后，即可在此管理同步与分组。'}</span></div>}
              </div>
            </div>
          </>}

          {section === 'groups' && <>
            <div className="settings-section-head"><div><h1>分组管理</h1><p>按用途整理账户；删除分组会保留账户与邮件。</p></div><button data-ui="ST13" className="settings-button is-primary" type="button" onClick={() => groupInputRef.current?.focus()}><Plus size={15} />新建分组</button></div>
            <button className="settings-ungrouped" type="button" onClick={() => showGroupAccounts('ungrouped')}><Folder size={21} /><span><strong>未分组账户</strong><small>查看账户并整理所属分组</small></span><b>{accountsQuery.isSuccess ? accounts.filter(a => !a.group_id).length : '—'} 个</b></button>
            <label className="settings-search"><Search size={15} /><input type="search" aria-label="搜索分组" placeholder="搜索分组名称" value={groupSearch} onChange={event => setGroupSearch(event.target.value)} /></label>
            <Status value={feedback.groups} />
            {groupsQuery.isError && <div className="settings-feedback is-error" role="alert">加载分组失败：{errorMessage(groupsQuery.error)} <button className="settings-text-button" type="button" onClick={() => void groupsQuery.refetch()}>重试</button></div>}
            <div className="settings-group-list">
              {groupsQuery.isPending && <div className="settings-empty">正在加载分组…</div>}
              {groups.filter(group => group.name.toLowerCase().includes(groupSearch.trim().toLowerCase())).map(group => <div className="settings-group-row" key={group.id}>
                <span className="settings-group-icon"><Folder size={18} /></span>
                {editingGroup === group.id ? <form className="settings-group-editor" onSubmit={event => {
                  event.preventDefault()
                  if (!rename.trim()) return
                  void run('groups', '重命名分组', async () => {
                    await api.renameGroup(group.id, rename.trim())
                    const view = useMailStore.getState().view
                    if (view.type === 'group' && view.groupId === group.id) useMailStore.setState({ view: { ...view, groupName: rename.trim() } })
                    await refreshOrganization()
                    setEditingGroup(null)
                  }, '分组名称已更新')
                }}><input aria-label="分组名称" value={rename} onChange={event => setRename(event.target.value)} required maxLength={128} autoFocus disabled={pendingGroups} /><button className="settings-button" disabled={pendingGroups} type="submit">保存名称</button><button className="settings-text-button" type="button" disabled={pendingGroups} onClick={() => setEditingGroup(null)}>取消</button></form> : <>
                  <span className="settings-group-copy"><strong>{group.name}（{group.account_count || 0}）</strong><small>{group.account_count ? '点击账户数量查看成员' : '空分组，可移入账户'}</small></span>
                  <button className="settings-count" type="button" onClick={() => showGroupAccounts(group.id)} aria-label={`查看 ${group.name} 的账户`}>{group.account_count || 0} 个账户</button>
                  <button className="settings-icon-button" type="button" aria-label={`重命名 ${group.name}`} disabled={pendingGroups} onClick={() => { setEditingGroup(group.id); setRename(group.name) }}><Pencil size={15} /></button>
                  <button className="settings-icon-button is-danger" type="button" aria-label={`删除分组 ${group.name}`} disabled={pendingGroups} onClick={() => {
                    if (!confirmAction(`删除分组 ${group.name}？账号和邮件会保留，并从该分组移出。`)) return
                    void run('groups', '删除分组', async () => {
                      await api.deleteGroup(group.id)
                      const state = useMailStore.getState()
                      useMailStore.setState(state.view.type === 'group' && state.view.groupId === group.id
                        ? { view: { type: 'allInbox' }, listFilter: 'all', search: '', selectedKey: null, selectedIds: [] }
                        : { selectedKey: null, selectedIds: [] })
                      if (groupFilter === group.id) setGroupFilter('all')
                      if (bulkGroup === group.id) setBulkGroup('')
                      await resetGroupMailQueries()
                      await refreshOrganization()
                    }, '已删除')
                  }}><Trash2 size={15} /><span className="settings-sr-only">删除</span></button>
                </>}
              </div>)}
              {groupsQuery.isSuccess && !groups.length && <div className="settings-empty">还没有创建分组，账户可以直接保持未分组。</div>}
              {groups.length > 0 && !groups.some(group => group.name.toLowerCase().includes(groupSearch.trim().toLowerCase())) && <div className="settings-empty">没有匹配的分组</div>}
            </div>
            <form className="settings-group-editor settings-card" onSubmit={event => {
              event.preventDefault()
              if (!groupName.trim()) return
              void run('groups', '创建分组', async () => { await api.createGroup({ name: groupName.trim() }); setGroupName(''); await refreshOrganization() }, '分组已创建')
            }}><label className="settings-field"><span>新分组名称</span><input ref={groupInputRef} value={groupName} onChange={event => setGroupName(event.target.value)} placeholder="新分组名" maxLength={128} required disabled={pendingGroups} /></label><button type="submit" className="settings-button is-primary" disabled={pendingGroups}>创建</button></form>
          </>}

          {section === 'general' && <>
            <div className="settings-section-head"><div><h1>通用</h1><p>管理外观、时间与同步设置，以及登录安全。</p></div></div>
            <section className="settings-card"><h2>外观</h2><p>外观偏好仅应用于当前浏览器或桌面客户端。</p>
              <div className="settings-theme-grid" data-ui="ST06">{([
                ['light', '亮色', '清爽明亮', Sun], ['dark', '深色', '适合低光环境', Moon], ['system', '跟随系统', '匹配系统外观', Monitor],
              ] as const).map(([value, label, description, Icon]) => <button key={value} type="button" className={`settings-theme-card${theme === value ? ' is-active' : ''}`} aria-pressed={theme === value} aria-label={label} onClick={() => setTheme(value)}><span className={`settings-theme-preview theme-${value}`} aria-hidden="true"><i /><span><b /><b /><b /></span></span><span className="settings-theme-label"><Icon size={15} />{label}{theme === value && <Check size={15} />}</span><small>{description}</small></button>)}</div>
              <div className="settings-control-row"><div><strong>账号图标</strong><small>选择侧栏与账户列表中的标识方式</small></div><div className="settings-segmented" data-ui="ST07">{([['none', '不展示'], ['brand', '品牌图标'], ['initials', '首字母']] as const).map(([mode, label]) => <button type="button" key={mode} aria-pressed={accountIconMode === mode} onClick={() => setAccountIconMode(mode)}>{label}</button>)}</div></div>
            </section>
            <section className="settings-card"><h2>元素序号浮层</h2><p>展示界面元素唯一编号，便于定位与反馈。</p>
              <div className="settings-control-row"><div><strong>启用元素序号浮层</strong><small>是否允许通过快捷键唤出元素序号覆盖层</small></div><button type="button" className={`settings-switch${uiReferenceEnabled ? ' is-active' : ''}`} aria-pressed={uiReferenceEnabled} aria-label="启用元素序号浮层" onClick={() => setUiReferenceEnabled(!uiReferenceEnabled)}><span /></button></div>
              <div className="settings-control-row"><div><strong>唤出快捷键</strong><small>当前快捷键：{formatShortcut(uiReferenceShortcut || getDefaultShortcut())}</small></div>{uiReferenceShortcut && <button type="button" className="settings-button" onClick={() => setUiReferenceShortcut(null)}>恢复默认</button>}</div>
            </section>
            <section className="settings-card" data-ui="ST08"><h2>时间与同步</h2><p>保存到服务端，应用于当前实例。</p>
              {settingsQuery.isError && <div className="settings-feedback is-error" role="alert">加载设置失败：{errorMessage(settingsQuery.error)} <button className="settings-text-button" type="button" onClick={() => void settingsQuery.refetch()}>重试</button></div>}
              <form onSubmit={event => {
                event.preventDefault()
                const patch: Record<string, string> = {}
                if (timezone.trim() !== (saved.app_timezone || '')) patch.app_timezone = timezone.trim()
                if (timeoutSeconds.trim() !== (saved.mail_fetch_timeout_seconds || '')) patch.mail_fetch_timeout_seconds = timeoutSeconds.trim()
                if (!Object.keys(patch).length) { report('general', '没有改动'); return }
                if (patch.app_timezone) {
                  try { new Intl.DateTimeFormat('zh-CN', { timeZone: patch.app_timezone }).format() } catch { report('general', '请输入有效时区，例如 Asia/Shanghai 或 UTC', true); return }
                }
                const timeoutPatch = patch.mail_fetch_timeout_seconds
                if (timeoutPatch !== undefined && (!Number.isFinite(Number(timeoutPatch)) || Number(timeoutPatch) <= 0)) { report('general', '拉信超时必须为正数', true); return }
                void run('general', '保存设置', async () => { await api.updateSettings(patch); await qc.invalidateQueries({ queryKey: queryKeys.settings }); setDraft({}) }, '设置已保存')
              }}><fieldset disabled={pendingGeneral || !settingsQuery.isSuccess}><div className="settings-fields"><label className="settings-field" htmlFor="settings-timezone"><span>时区</span><input id="settings-timezone" list="settings-timezones" value={timezone} onChange={event => setDraft(current => ({ ...current, app_timezone: event.target.value }))} placeholder="Asia/Shanghai" /><small>使用 IANA 时区名称</small></label><datalist id="settings-timezones"><option value="Asia/Shanghai" /><option value="Asia/Tokyo" /><option value="America/New_York" /><option value="Europe/London" /><option value="UTC" /></datalist><label className="settings-field" htmlFor="settings-timeout"><span>拉信超时（秒）</span><input id="settings-timeout" type="number" step="any" value={timeoutSeconds} onChange={event => setDraft(current => ({ ...current, mail_fetch_timeout_seconds: event.target.value }))} placeholder="30" /><small>单次网络请求的等待上限（未设置时默认 30 秒）</small></label></div><button className="settings-button is-primary" type="submit">保存</button></fieldset></form><Status value={feedback.general} />
            </section>
            <section className="settings-card"><h2>登录安全</h2><p>修改应用登录密码，不会修改邮箱服务商密码。</p>
              <form data-ui="ST09" onSubmit={event => {
                event.preventDefault()
                if (newPassword !== confirmPassword) { report('password', '两次输入的新密码不一致', true); return }
                void run('password', '修改密码', async () => { await api.changePassword(currentPassword, newPassword); setCurrentPassword(''); setNewPassword(''); setConfirmPassword('') }, '密码已更新')
              }}><fieldset disabled={pendingPassword}><div className="settings-fields settings-password-fields"><label className="settings-field" htmlFor="current-password"><span>当前密码</span><input id="current-password" name="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} required /></label><label className="settings-field" htmlFor="new-password"><span>新密码</span><input id="new-password" name="new-password" type="password" autoComplete="new-password" minLength={8} value={newPassword} onChange={event => setNewPassword(event.target.value)} placeholder="至少 8 位" required /></label><label className="settings-field" htmlFor="confirm-password"><span>确认新密码</span><input id="confirm-password" name="confirm-password" type="password" autoComplete="new-password" minLength={8} value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} required /></label></div><button className="settings-button is-primary" type="submit">更新密码</button></fieldset></form><Status value={feedback.password} />
              <div className="settings-control-row"><div><strong>退出登录</strong><small>退出当前浏览器或桌面客户端会话</small></div><button data-ui="ST16" id="logout-button" type="button" className="settings-button is-danger" disabled={pendingPassword} onClick={() => void run('password', '退出登录', async () => { await api.logout(); qc.clear() })}>退出登录</button></div>
            </section>
          </>}
        </div>
      </div>
      {accountDialogOpen && <AccountDialog key={editingAccount?.id || 'new-account'} account={editingAccount || undefined} groups={groups} groupsAvailable={groupsQuery.isSuccess} onClose={() => { setAddOpen(false); setEditingAccount(null) }} onSaved={async groupId => {
        const wasEditing = editingAccount !== null
        if (editingAccount && (editingAccount.group_id || '') !== groupId) {
          useMailStore.setState({ selectedKey: null, selectedIds: [] })
          await resetGroupMailQueries()
        }
        await refreshOrganization()
        if (!wasEditing) await qc.resetQueries({ queryKey: queryKeys.stats })
        report('accounts', wasEditing ? '账户设置已更新' : '账户已添加')
        setAddOpen(false)
        setEditingAccount(null)
      }} />}
    </section>
  )
}
