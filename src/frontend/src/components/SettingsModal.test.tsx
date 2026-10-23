// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsModal'
import Sidebar from './Sidebar'
import { __resetCsrfForTests } from '../api/client'
import { queryClient, queryKeys } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { changeSelect, cleanup, click, render, typeInto, waitFor } from '../test/render'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const puts: Array<{ url: string; body: unknown }> = []

beforeEach(() => {
  puts.length = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const u = String(url)
    if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
    if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
    if (u === '/api/groups') return json({ groups: [] })
    if (u === '/api/settings') {
      if (init.method === 'PUT') {
        const parsed = JSON.parse(String(init.body))
        puts.push({ url: u, body: parsed })
        return json({ ok: true, settings: parsed.settings })
      }
      return json({
        settings: {
          app_timezone: 'Asia/Shanghai',
          mail_fetch_timeout_seconds: '120',
        },
      })
    }
    return json({ detail: 'unexpected' }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  __resetCsrfForTests()
  queryClient.clear()
})

describe('<SettingsModal />', () => {
  it('keeps a mobile navigation control available while settings replaces the list', async () => {
    const originalWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 })
    try {
      const { container } = await render(<SettingsPage />)
      const toggle = container.querySelector('[data-testid="sidebar-toggle"]') as HTMLButtonElement
      expect(toggle.getAttribute('aria-label')).toBe('打开导航')
      expect(toggle.getAttribute('aria-expanded')).toBe('false')

      await click(toggle)
      expect(useMailStore.getState().mobileSidebarOpen).toBe(true)
      expect(toggle.getAttribute('aria-label')).toBe('关闭导航')
      expect(toggle.getAttribute('aria-expanded')).toBe('true')

      await click(toggle)
      expect(useMailStore.getState().mobileSidebarOpen).toBe(false)
      expect(toggle.getAttribute('aria-expanded')).toBe('false')
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
    }
  })

  it('switches between tabs and loads general settings', async () => {
    const { container } = await render(<SettingsPage />)
    expect(container.querySelector('.settings-page')).not.toBeNull()

    // Switch to General tab
    const genBtn = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('通用')) || null
    await click(genBtn)
    await waitFor(() => {
      const el = container.querySelector('#settings-timezone') as HTMLInputElement
      expect(el?.value).toBe('Asia/Shanghai')
    })
    const tzInput = container.querySelector('#settings-timezone') as HTMLInputElement
    const timeoutInput = container.querySelector('#settings-timeout') as HTMLInputElement
    expect(timeoutInput.value).toBe('120')

    // Click save without modifications -> '没有改动'
    const saveBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '保存') || null
    await click(saveBtn)
    await waitFor(() => expect(container.textContent).toContain('没有改动'))
    expect(puts.length).toBe(0)

    // Modify timezone and timeout, then save
    await typeInto(tzInput, 'UTC')
    await typeInto(timeoutInput, '90')
    await click(saveBtn)

    await waitFor(() => {
      expect(puts).toEqual([
        {
          url: '/api/settings',
          body: {
            settings: {
              app_timezone: 'UTC',
              mail_fetch_timeout_seconds: '90',
            },
          },
        },
      ])
    })
    await waitFor(() => expect(container.textContent).toContain('设置已保存'))
  })

  it('renders logout button and calls logout API on click', async () => {
    const assignMock = vi.fn()
    vi.stubGlobal('window', Object.assign(new EventTarget(), { location: { assign: assignMock } }))

    let logoutCalled = false
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') return json({ groups: [] })
      if (u === '/api/settings') return json({ settings: {} })
      if (u === '/api/auth/logout') {
        logoutCalled = true
        return json({ ok: true })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    const genBtn = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('通用')) || null
    await click(genBtn)

    const logoutBtn = container.querySelector('#logout-button') as HTMLButtonElement
    expect(logoutBtn).not.toBeNull()
    await click(logoutBtn)

    await waitFor(() => {
      expect(logoutCalled).toBe(true)
      expect(assignMock).toHaveBeenCalledWith('/')
    })
  })

  it('displays error and does not redirect when logout fails with 500', async () => {
    const assignMock = vi.fn()
    vi.stubGlobal('window', Object.assign(new EventTarget(), { location: { assign: assignMock } }))

    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') return json({ groups: [] })
      if (u === '/api/settings') return json({ settings: {} })
      if (u === '/api/auth/logout') {
        return json({ detail: 'Server Error' }, 500)
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    const genBtn = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('通用')) || null
    await click(genBtn)

    const logoutBtn = container.querySelector('#logout-button') as HTMLButtonElement
    await click(logoutBtn)

    await waitFor(() => {
      expect(container.textContent).toContain('Server Error')
      expect(assignMock).not.toHaveBeenCalled()
    })
  })

  it('clears group name on successful creation, but preserves input on error', async () => {
    let shouldFail = true
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') {
        if (init.method === 'POST') {
          if (shouldFail) return json({ detail: 'duplicate group' }, 400)
          return json({ id: 'g1', name: 'Work' })
        }
        return json({ groups: [] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    const input = container.querySelector('input[placeholder="新分组名"]') as HTMLInputElement
    const createBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '创建') || null

    await typeInto(input, 'Work')
    await click(createBtn)

    // Failed: input remains 'Work'
    await waitFor(() => expect(container.textContent).toContain('duplicate group'))
    expect(input.value).toBe('Work')

    // Succeed: input is cleared
    shouldFail = false
    await click(createBtn)
    await waitFor(() => expect(container.textContent).toContain('分组已创建'))
    expect(input.value).toBe('')
  })

  it('keeps the settings group list and sidebar in sync after create and delete', async () => {
    let groups: Array<{ id: string; name: string; color: null; account_count: number; sort_order: number }> = []
    const accountId = 'settings-sync-account'
    const accountEmail = 'settings-sync@example.test'
    let groupId: string | null = null
    let revision = 0
    const groupReads: string[][] = []
    const accountReads: Array<string | null> = []
    const layoutReads: Array<string | null> = []
    const currentAccount = () => ({
      id: accountId, email: accountEmail, status: 'active', sync_status: 'idle',
      account_type: 'imap', provider: 'imap', group_id: groupId,
      group_name: groups.find((group) => group.id === groupId)?.name ?? null,
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init.method || 'GET'
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts' && method === 'GET') {
        accountReads.push(groupId)
        return json({ accounts: [currentAccount()], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (url.pathname === `/api/accounts/${accountId}` && method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as { group_id?: string; clear_group?: boolean }
        groupId = body.clear_group ? null : body.group_id ?? null
        revision += 1
        return json(currentAccount())
      }
      if (url.pathname === '/api/groups' && method === 'GET') {
        groupReads.push(groups.map((group) => group.name))
        return json({ groups })
      }
      if (url.pathname === '/api/groups' && method === 'POST') {
        const name = (JSON.parse(String(init.body)) as { name: string }).name
        const group = { id: 'created-group', name, color: null, account_count: 0, sort_order: groups.length }
        groups = [...groups, group]
        revision += 1
        return json(group)
      }
      if (url.pathname === '/api/groups/created-group' && method === 'DELETE') {
        groups = groups.filter((group) => group.id !== 'created-group')
        groupId = null
        revision += 1
        return new Response(null, { status: 204 })
      }
      if (url.pathname === '/api/sidebar/layout' && method === 'GET') {
        layoutReads.push(groupId)
        return json({
          revision: String(revision).padStart(64, '0'),
          group_ids: groups.map((group) => group.id),
          master_account_ids: [accountId],
          ungrouped_account_ids: groupId ? [] : [accountId],
          group_account_ids: Object.fromEntries(groups.map((group) => [group.id, groupId === group.id ? [accountId] : []])),
        })
      }
      if (url.pathname === '/api/mail/stats') return json({
        total_unread: 1,
        accounts: [{ account_id: accountId, unread_count: 1, total_count: 1 }],
      })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<><Sidebar /><SettingsPage /></>)
    const sidebar = container.querySelector('.tree-groups-section') as HTMLElement
    const settings = container.querySelector('.settings-page') as HTMLElement
    await waitFor(() => expect(container.querySelector(`.tree-account-block[data-drop-list="master"][data-account-id="${accountId}"]`)?.getAttribute('draggable')).toBe('true'))
    const input = settings.querySelector('input[placeholder="新分组名"]') as HTMLInputElement
    const createButton = [...settings.querySelectorAll('button')].find((button) => button.textContent === '创建') || null

    await typeInto(input, '由设置创建')
    await click(createButton)
    await waitFor(() => expect(sidebar.textContent).toContain('由设置创建'))
    await waitFor(() => expect(sidebar.querySelector('.tree-group-block[data-group-id="created-group"] .tree-group-heading')?.getAttribute('draggable')).toBe('true'))

    const moveSelect = settings.querySelector(`select[aria-label="移动 ${accountEmail}"]`) as HTMLSelectElement
    await changeSelect(moveSelect, 'created-group')
    await waitFor(() => expect(moveSelect.value).toBe('created-group'))
    const disclosure = sidebar.querySelector('button[aria-label="展开分组 由设置创建"]')
    if (disclosure) await click(disclosure)
    await waitFor(() => expect(sidebar.querySelector(`.tree-account-block[data-drop-list="group:created-group"][data-account-id="${accountId}"]`)?.getAttribute('draggable')).toBe('true'))
    expect(accountReads).toContain('created-group')
    expect(layoutReads).toContain('created-group')

    const priorAccountReads = accountReads.length
    const priorLayoutReads = layoutReads.length
    const deleteButton = [...settings.querySelectorAll('button')].filter((button) => button.textContent === '删除').at(-1) || null
    await click(deleteButton)
    await waitFor(() => expect(sidebar.textContent).not.toContain('由设置创建'))
    await waitFor(() => expect(queryClient.getQueryData<Array<{ id: string; group_id: string | null }>>(queryKeys.accounts)?.[0]?.group_id).toBeNull())
    await waitFor(() => expect(container.querySelector(`.tree-account-block[data-drop-list="master"][data-account-id="${accountId}"]`)?.getAttribute('draggable')).toBe('true'))
    expect(accountReads.length).toBeGreaterThan(priorAccountReads)
    expect(layoutReads.length).toBeGreaterThan(priorLayoutReads)
    expect(groups).toEqual([])
    expect(groupReads.some((names) => names.includes('由设置创建'))).toBe(true)
    expect(groupReads.at(-1)).toEqual([])
  })

  it('resets global unread statistics and mail lists after deleting the last account', async () => {
    let accountExists = true
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init.method || 'GET'
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts' && method === 'GET') {
        const accounts = accountExists ? [{
          id: 'account-delete', email: 'delete@example.test', status: 'active', sync_status: 'idle',
          account_type: 'imap', provider: 'imap', group_id: null,
        }] : []
        return json({ accounts, total: accounts.length, limit: 200, offset: 0, has_more: false })
      }
      if (url.pathname === '/api/accounts/account-delete' && method === 'DELETE') {
        accountExists = false
        return new Response(null, { status: 204 })
      }
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/sidebar/layout') return json({
        revision: String(accountExists ? 1 : 2).padStart(64, '0'),
        group_ids: [],
        master_account_ids: accountExists ? ['account-delete'] : [],
        ungrouped_account_ids: accountExists ? ['account-delete'] : [],
        group_account_ids: {},
      })
      if (url.pathname === '/api/mail/stats') {
        return json({ total_unread: accountExists ? 4 : 0, accounts: accountExists ? [{ account_id: 'account-delete', unread_count: 4, total_count: 4 }] : [] })
      }
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))
    queryClient.setQueryData(queryKeys.inbox(), ['old-mail'])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 4, byAccount: new Map([['account-delete', 4]]) })

    const { container } = await render(<><Sidebar /><SettingsPage /></>)
    const inbox = container.querySelector('button[aria-label="所有收件箱"]') as HTMLButtonElement
    await waitFor(() => expect(inbox.textContent).toContain('4'))
    const settings = container.querySelector('.settings-page') as HTMLElement
    await waitFor(() => expect(settings.textContent).toContain('delete@example.test'))
    const deleteButton = [...settings.querySelectorAll('button')].find((button) => button.textContent === '删除') || null
    await click(deleteButton)

    await waitFor(() => expect(inbox.textContent).not.toContain('4'))
    expect(queryClient.getQueryData(queryKeys.inbox())).toBeUndefined()
    expect(queryClient.getQueryData(queryKeys.stats)).toEqual({ totalUnread: 0, byAccount: new Map() })
  })

  it('refreshes global unread statistics after adding an account', async () => {
    let account: {
      id: string
      email: string
      status: string
      sync_status: string
      account_type: string
      provider: string
      group_id: null
    } | null = null
    let revision = 0
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init.method || 'GET'
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts' && method === 'GET') {
        const accounts = account ? [account] : []
        return json({ accounts, total: accounts.length, limit: 200, offset: 0, has_more: false })
      }
      if (url.pathname === '/api/accounts' && method === 'POST') {
        account = {
          id: 'account-added', email: 'added@example.test', status: 'active', sync_status: 'idle',
          account_type: 'imap', provider: 'imap', group_id: null,
        }
        revision += 1
        return json(account)
      }
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/sidebar/layout') return json({
        revision: String(revision).padStart(64, '0'),
        group_ids: [],
        master_account_ids: account ? [account.id] : [],
        ungrouped_account_ids: account ? [account.id] : [],
        group_account_ids: {},
      })
      if (url.pathname === '/api/mail/stats') return json({
        total_unread: account ? 2 : 0,
        accounts: account ? [{ account_id: account.id, unread_count: 2, total_count: 2 }] : [],
      })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 0, byAccount: new Map<string, number | null>() })

    const { container } = await render(<><Sidebar /><SettingsPage /></>)
    const inbox = container.querySelector('button[aria-label="所有收件箱"]') as HTMLButtonElement
    const settings = container.querySelector('.settings-page') as HTMLElement
    await typeInto(settings.querySelector('#account-email'), 'added@example.test')
    await typeInto(settings.querySelector('#account-imap-host'), 'imap.example.test')
    const addButton = [...settings.querySelectorAll('button')].find((button) => button.textContent === '添加') || null
    await click(addButton)

    await waitFor(() => expect(settings.textContent).toContain('账户已添加'))
    await waitFor(() => expect(inbox.textContent).toContain('2'))
    expect(queryClient.getQueryData<{ totalUnread: number }>(queryKeys.stats)?.totalUnread).toBe(2)
  })

  it('displays queued count message for sync-all without overwriting with generic text', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u.startsWith('/api/accounts/sync-all')) return json({ count: 7, enqueued: true })
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') return json({ groups: [] })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    const syncBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '同步全部账户') || null
    await click(syncBtn)

    await waitFor(() => {
      expect(container.textContent).toContain('已排队 7 个同步任务')
    })
  })

  it('deleting the group currently in view returns to all inbox and clears stale selection', async () => {
    const groups = [{ id: 'group-current', name: '当前分组', color: null, account_count: 1, sort_order: 0 }]
    const accounts = [{
      id: 'account-current', email: 'current@example.test', status: 'active', sync_status: 'idle',
      account_type: 'imap', provider: 'imap', group_id: 'group-current', group_name: '当前分组',
    }]
    const requests: Array<{ path: string; method: string }> = []
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init.method || 'GET'
      requests.push({ path: url.pathname, method })
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts') return json({ accounts, total: accounts.length, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups })
      if (url.pathname === '/api/groups/group-current' && method === 'DELETE') return new Response(null, { status: 204 })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))
    useMailStore.setState({
      view: { type: 'group', groupId: 'group-current', groupName: '当前分组', category: 'inbox' },
      listFilter: 'unread', search: 'stale query', selectedKey: 'stale-message', selectedIds: ['stale-message'], settingsOpen: true,
    })

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.textContent).toContain('当前分组（1）'))
    const deleteButtons = [...container.querySelectorAll('button')].filter((button) => button.textContent === '删除')
    await click(deleteButtons.at(-1) || null)

    await waitFor(() => expect(requests).toContainEqual({ path: '/api/groups/group-current', method: 'DELETE' }))
    const state = useMailStore.getState()
    expect(state.view).toEqual({ type: 'allInbox' })
    expect(state.listFilter).toBe('all')
    expect(state.search).toBe('')
    expect(state.selectedKey).toBeNull()
    expect(state.selectedIds).toEqual([])
    expect(state.settingsOpen).toBe(true)
  })

  it('clears selected message state after a successful account group change', async () => {
    const groups = [
      { id: 'group-one', name: '一组', color: null, account_count: 1, sort_order: 0 },
      { id: 'group-two', name: '二组', color: null, account_count: 0, sort_order: 1 },
    ]
    const account = {
      id: 'account-one', email: 'one@example.test', status: 'active', sync_status: 'idle',
      account_type: 'imap', provider: 'imap', group_id: 'group-one', group_name: '一组',
    }
    let currentGroupId: string | null = 'group-one'
    const updateBodies: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts/account-one' && init.method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as { group_id?: string; clear_group?: boolean }
        updateBodies.push(body)
        currentGroupId = body.clear_group ? null : body.group_id || null
        return json({ ...account, group_id: currentGroupId, group_name: groups.find((group) => group.id === currentGroupId)?.name || null })
      }
      if (url.pathname === '/api/accounts') return json({ accounts: [{ ...account, group_id: currentGroupId, group_name: groups.find((group) => group.id === currentGroupId)?.name || null }], total: 1, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))
    useMailStore.setState({ selectedKey: 'stale-message', selectedIds: ['stale-message'] })

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('select[aria-label="移动 one@example.test"]')).not.toBeNull())
    const groupSelect = container.querySelector('select[aria-label="移动 one@example.test"]') as HTMLSelectElement
    await changeSelect(groupSelect, 'group-two')
    await waitFor(() => expect(updateBodies[0]).toEqual({ group_id: 'group-two' }))
    await waitFor(() => expect(groupSelect.value).toBe('group-two'))
    await changeSelect(groupSelect, '')
    await waitFor(() => expect(updateBodies[1]).toEqual({ clear_group: true }))
    expect(useMailStore.getState().selectedKey).toBeNull()
    expect(useMailStore.getState().selectedIds).toEqual([])
  })
})
