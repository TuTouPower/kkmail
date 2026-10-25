// @vitest-environment jsdom
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Sidebar from './Sidebar'
import { useMailStore } from '../store/mailStore'
import { setReadOptimistic } from '../api/queries'
import { __resetCsrfForTests } from '../api/client'
import { cleanup, render, waitFor, click, typeInto } from '../test/render'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const groups = [
  { id: 'group-1', name: '税务归档', color: null, account_count: 1, sort_order: 0 },
  { id: 'group-2', name: '归档项目', color: null, account_count: 0, sort_order: 1 },
]
const accounts = [
  { id: 'acc-1', email: 'finance@z.example', status: 'active', account_type: 'imap', provider: 'imap', group_id: 'group-1', group_name: '税务归档' },
  { id: 'acc-2', email: 'notes@a.example', status: 'active', account_type: 'imap', provider: 'imap', group_id: null },
]

function mockApi(options: { failAccounts?: boolean; failStats?: boolean; partialStats?: boolean; failAcc1Stats?: boolean; failAcc2Stats?: boolean; missingInboxAcc1?: boolean; duplicateInboxFoldersAcc1?: boolean; nonSelectableParentAcc1?: boolean; emptyFoldersAcc1?: boolean; syncStatusAcc1?: string; disabledAcc1?: boolean; disabledAcc2?: boolean; displayNameAcc1?: string; additionalAccounts?: Array<{ id: string; email: string; group_id: string | null; display_name?: string }>; failLayout?: boolean; staleLayout?: boolean; renameResponse?: () => Promise<Response> } = {}) {
  const calls: Array<{ url: string; method: string; body?: string }> = []
  let acc1Unread = 2
  let acc2Unread = 1
  const initialAccounts: Array<{
    id: string
    email: string
    status: string
    account_type: string
    provider: string
    group_id: string | null
    group_name?: string
    display_name?: string
  }> = [
    ...accounts.map((account) => ({ ...account, group_id: account.group_id ?? null })),
    ...(options.additionalAccounts || []).map((account) => ({
      id: account.id,
      email: account.email,
      status: 'active',
      account_type: 'imap',
      provider: 'imap',
      group_id: account.group_id,
      group_name: account.group_id === 'group-2' ? '归档项目' : undefined,
      display_name: account.display_name,
    })),
  ]
  let currentAccounts: Array<{
    id: string
    email: string
    status: string
    sync_status?: string
    account_type: string
    provider: string
    group_id: string | null
    group_name?: string
    display_name?: string
    sync_enabled?: boolean
  }> = initialAccounts.map((account) => ({
    ...account,
    group_id: account.group_id ?? null,
    display_name: account.id === 'acc-1' ? options.displayNameAcc1 : account.display_name,
    sync_enabled: account.id === 'acc-1' ? !options.disabledAcc1 : !options.disabledAcc2,
    sync_status: account.id === 'acc-1' && options.syncStatusAcc1 ? options.syncStatusAcc1 : 'idle',
  }))
  let currentGroups = groups.map((group) => ({ ...group }))
  let revision = 0
  let currentLayout: {
    revision: string
    group_ids: string[]
    master_account_ids: string[]
    ungrouped_account_ids: string[]
    group_account_ids: Record<string, string[]>
  } = {
    revision: String(revision).padStart(64, '0'),
    group_ids: groups.map((group) => group.id),
    master_account_ids: ['acc-2', 'acc-1', ...((options.additionalAccounts || []).map((account) => account.id))],
    ungrouped_account_ids: ['acc-2', ...((options.additionalAccounts || []).filter((account) => !account.group_id).map((account) => account.id))],
    group_account_ids: {
      'group-1': ['acc-1'],
      'group-2': (options.additionalAccounts || []).filter((account) => account.group_id === 'group-2').map((account) => account.id),
    },
  }
  vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = init?.method || 'GET'
    calls.push({ url: url.pathname + url.search, method, body: typeof init?.body === 'string' ? init.body : undefined })
    if (url.pathname === '/api/auth/me') return json({ csrf_token: 'test-csrf' })
    if (url.pathname === '/api/sidebar/layout' && method === 'GET') return json(currentLayout)
    if (url.pathname === '/api/groups' && method === 'GET') return json({ groups: currentGroups })
    if (url.pathname.startsWith('/api/groups/') && method === 'PATCH') {
      if (options.renameResponse) return options.renameResponse()
      const id = url.pathname.split('/').at(-1)!
      const name = JSON.parse(String(init?.body)).name as string
      currentGroups = currentGroups.map((group) => group.id === id ? { ...group, name } : group)
      currentAccounts = currentAccounts.map((account) => account.group_id === id ? { ...account, group_name: name } : account)
      revision += 1
      currentLayout = { ...currentLayout, revision: String(revision).padStart(64, '0') }
      return json({ id, name, color: null, account_count: 1, sort_order: 0 })
    }
    if (url.pathname.startsWith('/api/groups/') && method === 'DELETE') {
      const id = url.pathname.split('/').at(-1)!
      currentGroups = currentGroups.filter((group) => group.id !== id)
      currentAccounts = currentAccounts.map((account) => account.group_id === id ? { ...account, group_id: null, group_name: undefined } : account)
      currentLayout = {
        ...currentLayout,
        group_ids: currentLayout.group_ids.filter((groupId) => groupId !== id),
        ungrouped_account_ids: currentLayout.master_account_ids.filter((accountId) => !currentAccounts.find((account) => account.id === accountId)?.group_id),
        group_account_ids: Object.fromEntries(Object.entries(currentLayout.group_account_ids).filter(([groupId]) => groupId !== id)),
      }
      revision += 1
      currentLayout = { ...currentLayout, revision: String(revision).padStart(64, '0') }
      return new Response(null, { status: 204 })
    }
    if (url.pathname === '/api/groups' && method === 'POST') {
      const newGroup = { id: 'group-new', name: JSON.parse(String(init?.body)).name as string, color: null, account_count: 0, sort_order: currentGroups.length }
      currentGroups = [...currentGroups, newGroup]
      currentLayout = {
        ...currentLayout,
        group_ids: [...currentLayout.group_ids, newGroup.id],
        group_account_ids: { ...currentLayout.group_account_ids, [newGroup.id]: [] },
      }
      revision += 1
      currentLayout = { ...currentLayout, revision: String(revision).padStart(64, '0') }
      return json(newGroup)
    }
    if (url.pathname === '/api/accounts') {
      if (options.failAccounts) return json({ detail: 'DB connection failed' }, 500)
      const byId = new Map(currentAccounts.map((account) => [account.id, account]))
      const orderedAccounts = currentLayout.master_account_ids.map((id) => byId.get(id)).filter((account) => account !== undefined)
      return json({ accounts: orderedAccounts, total: orderedAccounts.length, limit: 200, offset: 0, has_more: false })
    }
    if (url.pathname === '/api/mail/stats') {
      if (options.failStats) return json({ detail: 'stats unavailable' }, 500)
      if (options.disabledAcc1 && options.disabledAcc2) return json({ total_unread: 0, accounts: [] })
      if (options.disabledAcc1) return json({ total_unread: 1, accounts: [
        { account_id: 'acc-2', unread_count: acc2Unread, total_count: 4 },
      ] })
      if (options.partialStats) return json({ total_unread: acc2Unread, accounts: [{ account_id: 'acc-2', unread_count: acc2Unread, total_count: 4 }] })
      return json({ total_unread: acc1Unread + acc2Unread, accounts: [
      { account_id: 'acc-1', unread_count: acc1Unread, total_count: 9 },
      { account_id: 'acc-2', unread_count: acc2Unread, total_count: 4 },
    ] })
    }
    if (url.pathname.startsWith('/api/mail/messages/') && url.pathname.endsWith('/read') && method === 'POST') {
      const messageId = url.pathname.split('/').at(-2) || ''
      if (messageId === 'read-acc1') acc1Unread = Math.max(0, acc1Unread - 1)
      return json({ id: messageId, is_read: true })
    }
    if (url.pathname === '/api/mail/accounts/acc-1/folder-stats') {
      if (options.failAcc1Stats) return json({ detail: 'folder stats unavailable' }, 500)
      if (options.emptyFoldersAcc1) return json({ account_id: 'acc-1', folders: [] })
      if (options.duplicateInboxFoldersAcc1) return json({ account_id: 'acc-1', folders: [
        { folder_id: 'inbox-1', remote_id: 'INBOX', name: 'INBOX', role: 'inbox', unread_count: 2, total_count: 9, parent_remote_id: null },
        { folder_id: 'inbox-alias', remote_id: '收件箱', name: '收件箱', role: 'inbox', unread_count: 0, total_count: 0, parent_remote_id: null },
      ] })
      if (options.nonSelectableParentAcc1) return json({ account_id: 'acc-1', folders: [
        { folder_id: 'other-parent', remote_id: 'Other', name: '其他文件夹', role: 'other', sync_status: 'paused', unread_count: null, total_count: null, parent_remote_id: null },
        { folder_id: 'qq-subscription', remote_id: 'Other/QQ邮件订阅', name: 'QQ邮件订阅', role: 'other', sync_status: 'idle', unread_count: 0, total_count: 0, parent_remote_id: 'Other' },
      ] })
      if (options.missingInboxAcc1) return json({ account_id: 'acc-1', folders: [
        { folder_id: 'sent-1', remote_id: 'Sent', name: 'Sent', role: 'sent', unread_count: 4, total_count: 8 },
        { folder_id: 'other-1', remote_id: 'Other', name: 'Other', role: 'other', unread_count: 6, total_count: 10 },
      ] })
      return json({ account_id: 'acc-1', folders: [
      { folder_id: 'inbox-1', remote_id: 'INBOX', name: 'INBOX', role: 'inbox', unread_count: 2, total_count: 9, parent_remote_id: null },
      { folder_id: 'drafts-1', remote_id: 'Drafts', name: 'Drafts', role: 'drafts', unread_count: 0, total_count: 1, parent_remote_id: null },
      { folder_id: 'work-child', remote_id: 'Work/Invoices', name: 'Invoices', role: 'other', unread_count: 0, total_count: 3, parent_remote_id: 'Work' },
      { folder_id: 'work', remote_id: 'Work', name: 'Work', role: 'other', unread_count: 0, total_count: 0, parent_remote_id: null },
    ] })
    }
    if (url.pathname === '/api/mail/accounts/acc-2/folder-stats') {
      if (options.failAcc2Stats) return json({ detail: 'folder stats unavailable' }, 500)
      return json({ account_id: 'acc-2', folders: [{ folder_id: 'inbox-2', remote_id: 'INBOX', name: 'INBOX', role: 'inbox', unread_count: 1, total_count: 4 }] })
    }
    if (url.pathname === '/api/sidebar/layout' && method === 'PUT') {
      if (options.failLayout) return json({ detail: 'layout failed' }, 500)
      const layout = JSON.parse(String(init?.body)) as {
        expected_revision: string
        group_ids: string[]
        master_account_ids: string[]
        ungrouped_account_ids: string[]
        group_account_ids: Record<string, string[]>
      }
      if (options.staleLayout || layout.expected_revision !== currentLayout.revision) return json({ detail: 'stale layout' }, 409)
      const ownerByAccount = new Map<string, string>()
      for (const [groupId, memberIds] of Object.entries(layout.group_account_ids)) {
        for (const id of memberIds) ownerByAccount.set(id, groupId)
      }
      const ungrouped = new Set(layout.ungrouped_account_ids)
      currentAccounts = currentAccounts.map((account) => ({
        ...account,
        group_id: ownerByAccount.get(account.id) || (ungrouped.has(account.id) ? null : account.group_id),
      }))
      revision += 1
      currentLayout = {
        revision: String(revision).padStart(64, '0'),
        group_ids: layout.group_ids,
        master_account_ids: layout.master_account_ids,
        ungrouped_account_ids: layout.ungrouped_account_ids,
        group_account_ids: layout.group_account_ids,
      }
      return new Response(null, { status: 204 })
    }
    if (url.pathname === '/api/sidebar/layout/default-order') {
      if (options.failLayout) return json({ detail: 'layout failed' }, 500)
      const body = JSON.parse(String(init?.body || '{}')) as { expected_revision: string }
      if (body.expected_revision !== currentLayout.revision) return json({ detail: 'stale layout' }, 409)
      revision += 1
      currentLayout = { ...currentLayout, revision: String(revision).padStart(64, '0') }
      return new Response(null, { status: 204 })
    }
    return json({ detail: `unexpected ${url.pathname}` }, 404)
  }))
  return calls
}

function createDataTransfer() {
  let payload = ''
  return { effectAllowed: '', dropEffect: '', setData: vi.fn((_type: string, value: string) => { payload = value }), getData: vi.fn(() => payload) }
}

function dispatchDrag(element: Element, type: 'dragstart' | 'dragend' | 'drop', dataTransfer = createDataTransfer()) {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: dataTransfer })
  element.dispatchEvent(event)
  return dataTransfer
}

describe('<Sidebar />', () => {
  beforeEach(() => {
    useMailStore.setState({
      view: { type: 'allInbox' }, listFilter: 'all',
      mobileSidebarOpen: false,
      sidebarSections: { allAccounts: true, accountList: true },
      expandedSidebarGroups: [], expandedSidebarCategories: [], expandedSidebarAccounts: [],
    })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    __resetCsrfForTests()
    localStorage.clear()
  })

  it('filters group and master account entries independently by email, domain, and display name', async () => {
    mockApi({
      displayNameAcc1: 'Finance Operations',
      additionalAccounts: [{ id: 'acc-3', email: 'records@b.example', group_id: 'group-2', display_name: 'Quarterly Reports' }],
    })
    useMailStore.setState({ expandedSidebarCategories: ['all:inbox', 'group:group-1:inbox', 'group:group-2:inbox'] })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="搜索分组 税务归档"]')).not.toBeNull())

    await click(container.querySelector('[aria-label="搜索分组 税务归档"]'))
    const groupOneSearch = container.querySelector('input[aria-label="搜索分组账号：税务归档"]') as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(groupOneSearch))
    await click(container.querySelector('[aria-label="搜索分组 归档项目"]'))
    await click(container.querySelector('[aria-label="搜索账号列表"]'))
    const groupTwoSearch = container.querySelector('input[aria-label="搜索分组账号：归档项目"]') as HTMLInputElement
    const masterSearch = container.querySelector('input[aria-label="搜索账号列表"]') as HTMLInputElement
    await waitFor(() => expect(document.activeElement).toBe(masterSearch))
    await typeInto(groupOneSearch, 'Z.EXAMPLE')
    await typeInto(groupTwoSearch, ' quarterly ')
    await typeInto(masterSearch, ' NOTES@A.EXAMPLE ')

    const groupOne = container.querySelector('[data-group-id="group-1"]')!
    const groupTwo = container.querySelector('[data-group-id="group-2"]')!
    const masterList = container.querySelector('.tree-account-list')!
    expect([...groupOne.querySelectorAll('.tree-account-block')].map((row) => row.getAttribute('data-account-id'))).toEqual(['acc-1'])
    expect([...groupTwo.querySelectorAll('.tree-account-block')].map((row) => row.getAttribute('data-account-id'))).toEqual(['acc-3'])
    expect([...masterList.querySelectorAll('.tree-account-block')].map((row) => row.getAttribute('data-account-id'))).toEqual(['acc-2'])
    expect(groupOne.querySelectorAll('.tree-category-account')).toHaveLength(1)
    expect(groupTwo.querySelectorAll('.tree-category-account')).toHaveLength(1)
    expect(container.querySelector('[data-ui="SB12"]')?.closest('.tree-section')?.querySelectorAll('.tree-category-account')).toHaveLength(3)
    expect(groupOne.querySelector('.tree-count')?.textContent).toBe('1')
    expect(useMailStore.getState().view).toEqual({ type: 'allInbox' })
    expect(useMailStore.getState().search).toBe('')
  })

  it('shows no matches for disabled accounts and restores local expansion and focus when search closes', async () => {
    mockApi({ disabledAcc1: true, displayNameAcc1: 'Finance Operations' })
    useMailStore.setState({ sidebarSections: { allAccounts: true, accountList: false } })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="搜索分组 税务归档"]')).not.toBeNull())
    const groupTrigger = container.querySelector('[aria-label="搜索分组 税务归档"]') as HTMLButtonElement
    await click(groupTrigger)
    const groupSearch = container.querySelector('input[aria-label="搜索分组账号：税务归档"]') as HTMLInputElement
    await typeInto(groupSearch, 'finance')
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .tree-no-search-results')?.textContent).toBe('未找到匹配账号'))
    expect(container.querySelector('[data-group-id="group-1"] .tree-account-block[data-account-id="acc-1"]')).toBeNull()
    expect(localStorage.getItem('mail-ui-storage')).not.toContain('finance')
    await click(container.querySelector('[aria-label="清除分组搜索 税务归档"]'))
    expect(groupSearch.value).toBe('')
    await waitFor(() => expect(document.activeElement).toBe(groupSearch))
    expect(container.querySelector('[data-group-id="group-1"] .tree-no-search-results')).toBeNull()
    await typeInto(groupSearch, 'finance')
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .tree-no-search-results')).not.toBeNull())

    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    await act(async () => { groupSearch.dispatchEvent(escape) })
    await waitFor(() => {
      expect(container.querySelector('input[aria-label="搜索分组账号：税务归档"]')).toBeNull()
      expect(container.querySelector('[data-group-id="group-1"] .tree-group-children')).toBeNull()
      expect(document.activeElement).toBe(groupTrigger)
    })

    const masterTrigger = container.querySelector('[aria-label="搜索账号列表"]') as HTMLButtonElement
    await click(masterTrigger)
    const masterSearch = container.querySelector('input[aria-label="搜索账号列表"]') as HTMLInputElement
    expect(masterSearch).not.toBeNull()
    expect(container.querySelector('.tree-account-list')).not.toBeNull()
    await typeInto(masterSearch, 'will-clear')
    await click(container.querySelector('[aria-label="清除账号列表搜索"]'))
    expect(masterSearch.value).toBe('')
    await waitFor(() => expect(document.activeElement).toBe(masterSearch))
    await typeInto(masterSearch, 'not-found')
    await click(container.querySelector('[aria-label="关闭账号列表搜索"]'))
    await waitFor(() => {
      expect(container.querySelector('input[aria-label="搜索账号列表"]')).toBeNull()
      expect(container.querySelector('.tree-account-list')).toBeNull()
      expect(document.activeElement).toBe(masterTrigger)
    })
    expect(useMailStore.getState().sidebarSections.accountList).toBe(false)
    await click(masterTrigger)
    expect((container.querySelector('input[aria-label="搜索账号列表"]') as HTMLInputElement).value).toBe('')
  })

  it('disables account dragging and drop targets inside filtered group and master lists', async () => {
    const calls = mockApi({ additionalAccounts: [{ id: 'acc-3', email: 'records@b.example', group_id: 'group-2' }] })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-list .tree-account-block[data-account-id="acc-2"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="搜索分组 税务归档"]'))
    await typeInto(container.querySelector('input[aria-label="搜索分组账号：税务归档"]'), 'finance')

    const groupOne = container.querySelector('[data-group-id="group-1"]')!
    const filteredAccount = groupOne.querySelector('.tree-account-block[data-account-id="acc-1"]')!
    const groupHeading = groupOne.querySelector('.tree-group-heading')!
    expect(filteredAccount.getAttribute('draggable')).toBe('false')
    expect(groupHeading.getAttribute('draggable')).toBe('false')
    const blockedStart = new Event('dragstart', { bubbles: true, cancelable: true })
    Object.defineProperty(blockedStart, 'dataTransfer', { value: createDataTransfer() })
    filteredAccount.dispatchEvent(blockedStart)
    expect(blockedStart.defaultPrevented).toBe(true)
    const sourceTransfer = dispatchDrag(container.querySelector('.tree-account-list .tree-account-block[data-account-id="acc-2"]')!, 'dragstart')
    const blockedGroupDrop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(blockedGroupDrop, 'dataTransfer', { value: sourceTransfer })
    groupOne.dispatchEvent(blockedGroupDrop)
    expect(blockedGroupDrop.defaultPrevented).toBe(true)
    expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(0)

    await click(container.querySelector('[aria-label="搜索账号列表"]'))
    await typeInto(container.querySelector('input[aria-label="搜索账号列表"]'), 'notes')
    const masterList = container.querySelector('.tree-account-list')!
    expect(masterList.querySelector('.tree-account-block[data-account-id="acc-2"]')?.getAttribute('draggable')).toBe('false')
    await click(container.querySelector('[aria-label="展开分组 归档项目"]'))
    const groupAccount = container.querySelector('[data-group-id="group-2"] .tree-account-block[data-account-id="acc-3"]')!
    const groupTransfer = dispatchDrag(groupAccount, 'dragstart')
    const blockedMasterDrop = new Event('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(blockedMasterDrop, 'dataTransfer', { value: groupTransfer })
    masterList.dispatchEvent(blockedMasterDrop)
    expect(blockedMasterDrop.defaultPrevented).toBe(true)
    expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(0)
  })

  it('keeps all six existing global categories and renders only user groups', async () => {
    const calls = mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelectorAll('[data-ui="SB13"]')).toHaveLength(6))
    expect(container.textContent).toContain('所有账号')
    for (const label of ['所有收件箱', '所有未读', '已发邮件', '草稿箱', '废纸篓', '垃圾邮件']) {
      expect(container.textContent).toContain(label)
    }
    await waitFor(() => expect(container.textContent).toContain('税务归档'))
    expect(container.textContent).not.toContain('工作')
    expect(container.textContent).not.toContain('个人')
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .unread-badge')?.textContent).toBe('2'))
    expect(calls.filter((call) => call.url.includes('group_id=')).length).toBe(0)
    const globalInbox = [...container.querySelectorAll('.tree-category-row')].find((row) => row.textContent?.includes('所有收件箱'))
    expect(globalInbox?.querySelector('.unread-badge')?.textContent).toBe('3')
    await click(container.querySelector('[aria-label="展开 所有收件箱"]'))
    await waitFor(() => expect(container.querySelectorAll('.tree-category-account')).toHaveLength(2))
    const inboxAccountBadges = [...container.querySelectorAll('.tree-category-account')].map((row) => row.querySelector('.unread-badge')?.textContent)
    expect(inboxAccountBadges).toEqual(['1', '2'])
  })

  it('hides disabled accounts from every sidebar entry without changing the full layout snapshot', async () => {
    const calls = mockApi({ disabledAcc1: true })
    useMailStore.setState({
      view: { type: 'account', accountId: 'acc-1', email: 'finance@z.example' },
      selectedKey: 'mail:acc-1:message-1',
      selectedIds: ['mail:acc-1:message-1'],
      search: 'stale search',
    })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(useMailStore.getState().view).toEqual({ type: 'allInbox' }))
    expect(useMailStore.getState().selectedKey).toBeNull()
    expect(useMailStore.getState().selectedIds).toEqual([])
    expect(useMailStore.getState().search).toBe('')
    expect(container.querySelector('.tree-account-block[data-account-id="acc-1"]')).toBeNull()
    expect(container.querySelector('.tree-account-block[data-account-id="acc-2"]')).not.toBeNull()
    await click(container.querySelector('[aria-label="展开 所有收件箱"]'))
    expect(container.querySelector('.tree-category-account')?.textContent).not.toContain('finance@z.example')
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    expect(container.querySelector('[data-group-id="group-1"] .tree-account-block[data-account-id="acc-1"]')).toBeNull()
    expect(container.querySelector('[data-group-id="group-1"] .tree-count')?.textContent).toBe('0')
    expect(calls.some((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toBe(false)
  })

  it('does not request disabled-account stats in the fallback path', async () => {
    const calls = mockApi({ disabledAcc1: true, failStats: true, failAcc1Stats: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-account-id="acc-2"] .unread-badge')?.textContent).toBe('1'))
    expect(calls.some((call) => call.url === '/api/mail/accounts/acc-1/folder-stats')).toBe(false)
    expect(calls.some((call) => call.url === '/api/mail/accounts/acc-2/folder-stats')).toBe(true)
  })

  it('shows zero unread and no account rows when all accounts are disabled', async () => {
    const calls = mockApi({ disabledAcc1: true, disabledAcc2: true, failStats: true, failAcc1Stats: true, failAcc2Stats: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block')).toBeNull())
    expect(container.querySelector('.unread-badge')).toBeNull()
    expect(calls.some((call) => call.url.includes('/folder-stats'))).toBe(false)
  })

  it('updates global, group, and account unread badges before the read request settles', async () => {
    mockApi()
    const originalFetch = vi.mocked(fetch)
    let releaseRead!: () => void
    let readStarted!: () => void
    const started = new Promise<void>((resolve) => { readStarted = resolve })
    const gate = new Promise<void>((resolve) => { releaseRead = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (String(url).endsWith('/read')) {
        readStarted()
        await gate
      }
      return originalFetch(url, init)
    }))
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .unread-badge')?.textContent).toBe('2'))
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))

    const mutation = setReadOptimistic([{
      id: 'read-acc1',
      subject: 'Unread',
      from: 'sender@example.test',
      is_read: false,
      is_flagged: false,
      has_attachments: false,
      accountEmail: 'finance@z.example',
      accountId: 'acc-1',
      locations: [{ folder_id: 'inbox-1', role: 'inbox' }],
    }], true)

    await started
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .unread-badge')?.textContent).toBe('1'))
    expect(container.querySelector('[data-ui="SB13"][aria-label="所有收件箱"] .unread-badge')?.textContent).toBe('2')
    expect(container.querySelector('.tree-account-block[data-account-id="acc-1"] .unread-badge')?.textContent).toBe('1')
    releaseRead()
    await mutation
    await waitFor(() => expect(container.querySelector('[data-ui="SB13"][aria-label="所有收件箱"] .unread-badge')?.textContent).toBe('2'))
  })

  it('focuses and traps keyboard focus inside the mobile navigation dialog', async () => {
    const previousWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    window.dispatchEvent(new Event('resize'))
    useMailStore.setState({ mobileSidebarOpen: true })
    mockApi()

    const { container } = await render(<Sidebar />)
    try {
      await waitFor(() => expect(container.querySelector('aside[role="dialog"][aria-modal="true"]')).not.toBeNull())
      const dialog = container.querySelector('aside[role="dialog"]')!
      const focusableElements = () => Array.from(dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.getAttribute('aria-hidden') !== 'true')

      await waitFor(() => expect(document.activeElement).toBe(focusableElements()[0]))
      await waitFor(() => expect(focusableElements().length).toBeGreaterThan(2))
      const focusable = focusableElements()
      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      last.focus()
      await act(async () => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
      })
      expect(document.activeElement).toBe(first)

      first.focus()
      await act(async () => {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }))
      })
      expect(document.activeElement).toBe(last)
    } finally {
      useMailStore.getState().closeMobileSidebar()
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: previousWidth })
      window.dispatchEvent(new Event('resize'))
    }
  })

  it('opens a group, navigates all categories, and expands the same account in both lists', async () => {
    mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="展开分组 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const groupCategories = container.querySelectorAll('.tree-group-children .tree-category-row')
    expect(groupCategories).toHaveLength(6)
    await click([...groupCategories].find((node) => node.textContent?.includes('所有未读')) || null)
    expect(useMailStore.getState().view).toEqual({ type: 'group', groupId: 'group-1', groupName: '税务归档', category: 'unread' })
    expect(useMailStore.getState().listFilter).toBe('unread')

    const masterAccount = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')
    expect(masterAccount).not.toBeNull()
    await click(masterAccount?.querySelector('.tree-disclosure') || null)
    await waitFor(() => expect(masterAccount?.textContent).toContain('收件箱'))
    expect(masterAccount?.querySelector('.tree-folder-row')).not.toBeNull()
  })

  it('disambiguates same-role folders while keeping each folder id navigable', async () => {
    mockApi({ duplicateInboxFoldersAcc1: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-account-id="acc-1"] .tree-disclosure')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-account-id="acc-1"]')!
    await click(account.querySelector('.tree-disclosure'))

    await waitFor(() => expect(
      [...account.querySelectorAll('.tree-folder-row')]
        .filter((row) => row.querySelector('.tree-label')?.textContent?.startsWith('收件箱')),
    ).toHaveLength(2))
    const inboxRows = [...account.querySelectorAll('.tree-folder-row')]
      .filter((row) => row.querySelector('.tree-label')?.textContent?.startsWith('收件箱'))
    const labels = inboxRows.map((row) => row.querySelector('.tree-label')?.textContent)
    expect(new Set(labels).size).toBe(2)

    const inboxRow = inboxRows.find((row) => row.querySelector('.tree-label')?.textContent?.includes('INBOX'))!
    const aliasRow = inboxRows.find((row) => row !== inboxRow)!
    await click(inboxRow)
    expect(useMailStore.getState().view).toMatchObject({ type: 'folder', folderId: 'inbox-1' })
    await click(aliasRow)
    expect(useMailStore.getState().view).toMatchObject({ type: 'folder', folderId: 'inbox-alias' })
  })

  it('shows a noselect parent as a disabled container without an unknown-count badge', async () => {
    mockApi({ nonSelectableParentAcc1: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-account-id="acc-1"] .tree-disclosure')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-account-id="acc-1"]')!
    await click(account.querySelector('.tree-disclosure'))

    await waitFor(() => expect(account.textContent).toContain('QQ邮件订阅'))
    const parentRow = [...account.querySelectorAll('.tree-folder-row')]
      .find((row) => row.querySelector('.tree-label')?.textContent === '其他文件夹') as HTMLButtonElement
    const childRow = [...account.querySelectorAll('.tree-folder-row')]
      .find((row) => row.querySelector('.tree-label')?.textContent === 'QQ邮件订阅')
    expect(parentRow.disabled).toBe(true)
    expect(parentRow.querySelector('.unread-badge')).toBeNull()
    expect(childRow?.getAttribute('style')).toContain('padding-left: 72px')

    await click(childRow ?? null)
    expect(useMailStore.getState().view).toMatchObject({ type: 'folder', folderId: 'qq-subscription' })
  })

  it('persists account-list reorder without changing existing group membership', async () => {
    const calls = mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelectorAll('.tree-account-block[data-drop-list="master"]')).toHaveLength(2))
    const source = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')!
    const dataTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', dataTransfer) })
    await act(async () => { dispatchDrag(target, 'drop', dataTransfer) })
    await waitFor(() => expect(calls.some((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toBe(true))
    const request = calls.find((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')
    const body = JSON.parse(request?.body || '{}')
    expect(body.master_account_ids).toEqual(['acc-2', 'acc-1'])
    expect(body.group_account_ids['group-1']).toEqual(['acc-1'])
    expect(body.ungrouped_account_ids).toEqual(['acc-2'])
  })

  it('clears selected message state after a successful account membership change', async () => {
    const calls = mockApi()
    useMailStore.setState({ selectedKey: 'mail-acc-2', selectedIds: ['mail-acc-2'] })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="展开分组 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const source = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')!
    const dataTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', dataTransfer) })
    await act(async () => { dispatchDrag(target, 'drop', dataTransfer) })
    await waitFor(() => expect(calls.some((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toBe(true))
    const request = calls.find((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')
    expect(JSON.parse(request?.body || '{}').group_account_ids['group-1']).toEqual(['acc-2', 'acc-1'])
    expect(useMailStore.getState().selectedKey).toBeNull()
    expect(useMailStore.getState().selectedIds).toEqual([])
  })

  it('moves a grouped account to the ungrouped list when dropped on a master-list account row', async () => {
    const calls = mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="展开分组 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const source = container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const dataTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', dataTransfer) })
    await act(async () => { dispatchDrag(target, 'drop', dataTransfer) })
    await waitFor(() => expect(calls.some((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toBe(true))
    const body = JSON.parse(calls.find((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')?.body || '{}')
    expect(body.group_account_ids['group-1']).toEqual([])
    expect(body.ungrouped_account_ids).toEqual(['acc-1', 'acc-2'])
  })

  it('refreshes the derived group unread badge after account membership changes', async () => {
    const calls = mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .unread-badge')?.textContent).toBe('2'))
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const source = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')!
    const dataTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', dataTransfer) })
    await act(async () => { dispatchDrag(target, 'drop', dataTransfer) })
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"] .unread-badge')?.textContent).toBe('3'))
    expect(calls.filter((call) => call.url === '/api/mail/stats').length).toBeGreaterThanOrEqual(2)
    expect(calls.some((call) => call.url.includes('group_id='))).toBe(false)
  })

  it('shows the backend account-load error and retries the account query', async () => {
    const calls = mockApi({ failAccounts: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.textContent).toContain('DB connection failed'), 3000)
    expect(container.querySelector('[role="alert"]')).not.toBeNull()
    expect(calls.some((call) => call.url.startsWith('/api/accounts'))).toBe(true)
  })

  it('reports a statistics-only failure separately from account loading', async () => {
    mockApi({ failStats: true, failAcc1Stats: true, failAcc2Stats: true })
    const { container } = await render(<Sidebar />)

    await waitFor(() => expect(container.querySelector('.tree-folder-status')?.textContent).toContain('未读统计暂不可用'), 3000)
    expect(container.querySelector('.tree-load-error')).toBeNull()
    expect(container.textContent).not.toContain('账户加载失败')
    expect(container.querySelector('.tree-folder-status .tree-retry')?.textContent).toBe('重试统计')
  })

  it('shows unknown global, account, and group unread counts when one account stats source fails', async () => {
    mockApi({ failStats: true, failAcc1Stats: true })
    const result = await render(<Sidebar />)
    await waitFor(() => expect(result.container.querySelector('.unread-badge-unknown')?.textContent).toBe('-'))
    expect(result.container.querySelector('[data-group-id="group-1"] .unread-badge-unknown')?.textContent).toBe('-')
    expect(result.container.querySelector('.tree-account-block[data-account-id="acc-1"] .unread-badge-unknown')?.textContent).toBe('-')
    expect(result.container.querySelectorAll('.unread-badge-unknown').length).toBeGreaterThanOrEqual(2)
  })

  it('treats accounts missing from a successful global stats response as unknown', async () => {
    mockApi({ partialStats: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-category-row[aria-label="所有收件箱"] .unread-badge-unknown')?.textContent).toBe('-'))
    expect(container.querySelector('[data-group-id="group-1"] .unread-badge-unknown')?.textContent).toBe('-')
    expect(container.querySelector('.tree-account-block[data-account-id="acc-1"] .unread-badge-unknown')?.textContent).toBe('-')
  })

  it('keeps inbox unread unknown when fallback folder stats have no inbox role', async () => {
    mockApi({ failStats: true, missingInboxAcc1: true })
    const { container } = await render(<Sidebar />)
    const inboxCategory = container.querySelector('.tree-category-row[aria-label="所有收件箱"]')
    await waitFor(() => expect(inboxCategory?.querySelector('.unread-badge')?.textContent).toBe('-'))
    await click(container.querySelector('[aria-label="展开 所有收件箱"]'))
    const financeAccount = container.querySelector('.tree-category-account[title="finance@z.example"]')
    await waitFor(() => expect(financeAccount?.querySelector('.unread-badge')?.textContent).toBe('-'))
  })

  it('retries a failed account folder-tree load', async () => {
    const calls = mockApi({ failAcc1Stats: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-account-id="acc-1"]')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-account-id="acc-1"]')!
    await click(account.querySelector('.tree-account-select'))

    await waitFor(() => expect(account.querySelector('.tree-folder-status')?.textContent).toContain('文件夹加载失败'), 3000)
    const retry = account.querySelector('.tree-folder-status .tree-retry') as HTMLButtonElement
    expect(retry.textContent).toBe('重试')
    const previousCalls = calls.filter((call) => call.url === '/api/mail/accounts/acc-1/folder-stats').length

    await click(retry)
    await waitFor(() => expect(calls.filter((call) => call.url === '/api/mail/accounts/acc-1/folder-stats').length).toBeGreaterThan(previousCalls))
  })

  it('account title and disclosure both toggle the folder tree without selecting a mail view', async () => {
    mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')!
    const title = account.querySelector('.tree-account-select')!
    expect(title.getAttribute('aria-expanded')).toBe('false')
    await click(title)
    expect(title.getAttribute('aria-expanded')).toBe('true')
    await waitFor(() => expect(account.textContent).toContain('收件箱'))
    expect(useMailStore.getState().view).toEqual({ type: 'allInbox' })
    await click(title)
    await waitFor(() => expect(account.textContent).not.toContain('收件箱'))
  })

  it('rejects a same-account drop and clears a cancelled group drag before an external drop', async () => {
    const calls = mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="展开分组 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const source = container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')!
    const transfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', transfer) })
    await act(async () => { dispatchDrag(source, 'drop', transfer) })
    expect(calls.some((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toBe(false)

    const group = container.querySelector('[data-group-id="group-1"] .tree-group-heading')!
    const groupTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(group, 'dragstart', groupTransfer) })
    await act(async () => { dispatchDrag(group, 'dragend', groupTransfer) })
    const external = createDataTransfer()
    external.setData('text/plain', 'external text')
    await act(async () => { dispatchDrag(container.querySelector('[data-group-id="group-2"]')!, 'drop', external) })
    expect(calls.some((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toBe(false)
  })

  it('prevents overlapping layout saves while the first save is pending', async () => {
    let release!: (response: Response) => void
    let layoutCalls = 0
    let revision = 0
    let layoutSnapshot: {
      revision: string
      group_ids: string[]
      master_account_ids: string[]
      ungrouped_account_ids: string[]
      group_account_ids: Record<string, string[]>
    } = {
      revision: String(revision).padStart(64, '0'),
      group_ids: ['group-1', 'group-2'],
      master_account_ids: ['acc-1', 'acc-2'],
      ungrouped_account_ids: ['acc-2'],
      group_account_ids: { 'group-1': ['acc-1'], 'group-2': [] },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'test-csrf' })
      if (url.pathname === '/api/groups') return json({ groups })
      if (url.pathname === '/api/accounts') {
        const byId = new Map(accounts.map((account) => [account.id, account]))
        const orderedAccounts = layoutSnapshot.master_account_ids.map((id) => byId.get(id)).filter((account) => account !== undefined)
        return json({ accounts: orderedAccounts, total: orderedAccounts.length, limit: 200, offset: 0, has_more: false })
      }
      if (url.pathname === '/api/mail/stats') return json({ total_unread: 3, accounts: [{ account_id: 'acc-1', unread_count: 2 }, { account_id: 'acc-2', unread_count: 1 }] })
      if (url.pathname === '/api/sidebar/layout' && (init?.method || 'GET') === 'GET') return json(layoutSnapshot)
      if (url.pathname === '/api/sidebar/layout' && init?.method === 'PUT') {
        layoutCalls += 1
        const layout = JSON.parse(String(init.body)) as {
          expected_revision: string
          group_ids: string[]
          master_account_ids: string[]
          ungrouped_account_ids: string[]
          group_account_ids: Record<string, string[]>
        }
        return new Promise<Response>((resolve) => {
          release = (response) => {
            if (response.status === 204) {
              revision += 1
              layoutSnapshot = { ...layout, revision: String(revision).padStart(64, '0') }
            }
            resolve(response)
          }
        })
      }
      return json({ detail: 'unexpected' }, 404)
    }))
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelectorAll('.tree-account-block[data-drop-list="master"]')).toHaveLength(2))
    const source = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')!
    const firstTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', firstTransfer); dispatchDrag(target, 'drop', firstTransfer) })
    await waitFor(() => expect(source.getAttribute('draggable')).toBe('false'))
    const secondTransfer = createDataTransfer()
    const rejectedDrag = new Event('dragstart', { bubbles: true, cancelable: true })
    Object.defineProperty(rejectedDrag, 'dataTransfer', { value: secondTransfer })
    await act(async () => { source.dispatchEvent(rejectedDrag) })
    expect(rejectedDrag.defaultPrevented).toBe(true)
    expect(layoutCalls).toBe(1)
    release(new Response(null, { status: 204 }))
    await waitFor(() => expect(source.getAttribute('draggable')).toBe('true'))
  })

  it('restores the rename input after a failed request and blocks resubmission while pending', async () => {
    let release!: (response: Response) => void
    let attempts = 0
    const calls = mockApi({ renameResponse: () => {
      attempts += 1
      return new Promise<Response>((resolve) => { release = resolve })
    } })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="分组操作 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="分组操作 税务归档"]'))
    await click([...container.querySelectorAll('[role="menuitem"]')].find((button) => button.textContent?.includes('重命名')) || null)
    const input = container.querySelector('input[aria-label="重命名分组"]') as HTMLInputElement
    await typeInto(input, 'Renamed')
    await click(container.querySelector('[aria-label="保存分组名称"]'))
    await waitFor(() => expect(input.disabled).toBe(true))
    expect(calls.filter((call) => call.method === 'PATCH')).toHaveLength(1)
    release(json({ detail: 'temporary failure' }, 500))
    await waitFor(() => expect(input.disabled).toBe(false))
    expect(input.value).toBe('Renamed')
    await click(container.querySelector('[aria-label="保存分组名称"]'))
    await waitFor(() => expect(input.disabled).toBe(true))
    expect(attempts).toBe(2)
    expect(calls.filter((call) => call.method === 'PATCH')).toHaveLength(2)
    release(json({ id: 'group-1', name: 'Renamed', color: null, account_count: 1, sort_order: 0 }))
    await waitFor(() => expect(container.querySelector('input[aria-label="重命名分组"]')).toBeNull())
  })

  it('returns focus to the new-group trigger after cancelling creation', async () => {
    mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="新建分组"]')).not.toBeNull())
    const trigger = container.querySelector('[aria-label="新建分组"]') as HTMLButtonElement
    await click(trigger)
    await click(container.querySelector('[aria-label="取消创建"]'))
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })

  it('closes the group management menu on Escape and restores its trigger focus', async () => {
    mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="分组操作 税务归档"]')).not.toBeNull())
    const trigger = container.querySelector('[aria-label="分组操作 税务归档"]') as HTMLButtonElement
    await click(trigger)
    expect(container.querySelector('[role="menu"]')).not.toBeNull()
    await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
    await waitFor(() => {
      expect(container.querySelector('[role="menu"]')).toBeNull()
      expect(document.activeElement).toBe(trigger)
    })
  })

  it('creates a user group and deletes it with confirmation while returning from its active view', async () => {
    const calls = mockApi()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    useMailStore.setState({
      view: { type: 'group', groupId: 'group-1', groupName: '税务归档', category: 'inbox' },
      listFilter: 'unread', selectedKey: 'group-message', selectedIds: ['group-message'],
    })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="新建分组"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="新建分组"]'))
    await typeInto(container.querySelector('input[aria-label="新分组名称"]'), '<自定义>')
    await click(container.querySelector('[aria-label="创建分组"]'))
    await waitFor(() => expect(calls.some((call) => call.url === '/api/groups' && call.method === 'POST')).toBe(true))
    expect(JSON.parse(calls.find((call) => call.url === '/api/groups' && call.method === 'POST')?.body || '{}').name).toBe('<自定义>')
    await waitFor(() => expect(container.querySelector('input[aria-label="新分组名称"]')).toBeNull())
    await waitFor(() => expect(container.querySelector('[data-group-id="group-new"]')?.textContent).toContain('<自定义>'))

    await click(container.querySelector('[aria-label="分组操作 税务归档"]'))
    await click([...container.querySelectorAll('[role="menuitem"]')].find((button) => button.textContent?.includes('删除')) || null)
    await waitFor(() => expect(calls.some((call) => call.url === '/api/groups/group-1' && call.method === 'DELETE')).toBe(true))
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"]')).toBeNull())
    expect(useMailStore.getState().view).toEqual({ type: 'allInbox' })
    expect(useMailStore.getState().listFilter).toBe('all')
    expect(useMailStore.getState().selectedKey).toBeNull()
    expect(useMailStore.getState().selectedIds).toEqual([])
    expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')).not.toBeNull()
    expect(container.querySelector('[data-group-id="group-1"]')).toBeNull()
  })

  it('shows the renamed group after server data refreshes', async () => {
    const calls = mockApi()
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="分组操作 税务归档"]'))
    await click([...container.querySelectorAll('[role="menuitem"]')].find((button) => button.textContent?.includes('重命名')) || null)
    const input = container.querySelector('input[aria-label="重命名分组"]') as HTMLInputElement
    await typeInto(input, '新税务分组')
    await click(container.querySelector('[aria-label="保存分组名称"]'))
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"]')?.textContent).toContain('新税务分组'))
    expect(calls.filter((call) => call.url === '/api/groups' && call.method === 'GET').length).toBeGreaterThanOrEqual(2)
  })

  it('preserves the group and its account when deletion confirmation is cancelled', async () => {
    const calls = mockApi()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[data-group-id="group-1"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="分组操作 税务归档"]'))
    await click([...container.querySelectorAll('[role="menuitem"]')].find((button) => button.textContent?.includes('删除')) || null)
    expect(calls.some((call) => call.url === '/api/groups/group-1' && call.method === 'DELETE')).toBe(false)
    expect(container.querySelector('[data-group-id="group-1"]')).not.toBeNull()
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    expect(container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')).not.toBeNull()
  })

  it('reports a failed layout save and leaves the queried membership unchanged', async () => {
    const calls = mockApi({ failLayout: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="展开分组 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const source = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')!
    const dataTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', dataTransfer) })
    await act(async () => { dispatchDrag(target, 'drop', dataTransfer) })
    await waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain('layout failed'))
    expect(calls.filter((call) => call.url === '/api/sidebar/layout' && call.method === 'PUT')).toHaveLength(1)
    expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')).not.toBeNull()
    expect(container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-2"]')).toBeNull()
  })

  it('refreshes the layout snapshot and asks for a new action after a stale revision conflict', async () => {
    const calls = mockApi({ staleLayout: true })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('[aria-label="展开分组 税务归档"]')).not.toBeNull())
    await click(container.querySelector('[aria-label="展开分组 税务归档"]'))
    const source = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')!
    const target = container.querySelector('.tree-account-block[data-drop-list="group:group-1"][data-account-id="acc-1"]')!
    const dataTransfer = createDataTransfer()
    await act(async () => { dispatchDrag(source, 'dragstart', dataTransfer) })
    await act(async () => { dispatchDrag(target, 'drop', dataTransfer) })
    await waitFor(() => expect(container.querySelector('[role="alert"]')?.textContent).toContain('已在其他窗口更新'))
    expect(calls.filter((call) => call.url === '/api/sidebar/layout' && call.method === 'GET').length).toBeGreaterThanOrEqual(2)
    expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-2"]')).not.toBeNull()
  })

  it('displays sync failure message and does not show virtual unread item when account folders are empty and sync_status is auth_failed (AC-001)', async () => {
    mockApi({ emptyFoldersAcc1: true, syncStatusAcc1: 'auth_failed' })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')!
    await click(account.querySelector('.tree-disclosure'))
    await waitFor(() => expect(account.textContent).toContain('同步失败，请检查账户设置'))
    expect(account.textContent).not.toContain('未读邮件')
  })

  it('shows sync failure on the account row and above existing folders', async () => {
    mockApi({ syncStatusAcc1: 'failed' })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')!
    expect(account.querySelector('[aria-label="同步失败"]')).not.toBeNull()

    await click(account.querySelector('.tree-disclosure'))
    await waitFor(() => expect(account.textContent).toContain('同步失败，请检查账户设置'))
    expect(account.textContent).toContain('收件箱')
  })

  it('displays no folders message when account folders are empty and sync_status is idle (AC-001)', async () => {
    mockApi({ emptyFoldersAcc1: true, syncStatusAcc1: 'idle' })
    const { container } = await render(<Sidebar />)
    await waitFor(() => expect(container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')).not.toBeNull())
    const account = container.querySelector('.tree-account-block[data-drop-list="master"][data-account-id="acc-1"]')!
    await click(account.querySelector('.tree-disclosure'))
    await waitFor(() => expect(account.textContent).toContain('暂无文件夹'))
    expect(account.textContent).not.toContain('未读邮件')
  })
})
