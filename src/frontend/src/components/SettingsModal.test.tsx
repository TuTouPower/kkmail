// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsModal'
import Sidebar from './Sidebar'
import { __resetCsrfForTests, UNAUTHORIZED_EVENT } from '../api/client'
import { queryClient, queryKeys } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { changeSelect, cleanup, click, render, typeInto, waitFor } from '../test/render'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const puts: Array<{ url: string; body: unknown }> = []
let settingsResponse: Record<string, string>

beforeEach(() => {
  settingsResponse = {
    app_timezone: 'Asia/Shanghai',
    mail_fetch_timeout_seconds: '120',
  }
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
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
      return json({ settings: settingsResponse })
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

  it('saves a timezone when the fetch timeout is unset', async () => {
    settingsResponse = { app_timezone: 'Asia/Shanghai' }
    const { container } = await render(<SettingsPage />)
    await click([...container.querySelectorAll('button')].find((button) => button.textContent?.includes('通用')) || null)

    const timezoneInput = container.querySelector('#settings-timezone') as HTMLInputElement
    await waitFor(() => expect(timezoneInput.value).toBe('Asia/Shanghai'))
    await typeInto(timezoneInput, 'UTC')
    await click([...container.querySelectorAll('button')].find((button) => button.textContent === '保存') || null)

    await waitFor(() => expect(puts).toEqual([
      { url: '/api/settings', body: { settings: { app_timezone: 'UTC' } } },
    ]))
  })

  it('saves a timeout without revalidating an unchanged timezone', async () => {
    settingsResponse = {
      app_timezone: 'Invalid/Zone',
      mail_fetch_timeout_seconds: '120',
    }
    const { container } = await render(<SettingsPage />)
    await click([...container.querySelectorAll('button')].find((button) => button.textContent?.includes('通用')) || null)

    const timeoutInput = container.querySelector('#settings-timeout') as HTMLInputElement
    await waitFor(() => expect(timeoutInput.value).toBe('120'))
    await typeInto(timeoutInput, '90')
    await click([...container.querySelectorAll('button')].find((button) => button.textContent === '保存') || null)

    await waitFor(() => expect(puts).toEqual([
      { url: '/api/settings', body: { settings: { mail_fetch_timeout_seconds: '90' } } },
    ]))
  })

  it('consumes an App-delivered OAuth return when no active flow exists', async () => {
    const activeFlowCalls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u === '/api/accounts/oauth/active') {
        activeFlowCalls.push(u)
        return json({ flow: null })
      }
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') return json({ groups: [] })
      if (u === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))
    window.location.hash = ''
    const consumed = vi.fn()

    await render(<SettingsPage oauthReturn onOAuthReturnConsumed={consumed} />)
    await waitFor(() => expect(consumed).toHaveBeenCalledOnce())

    expect(activeFlowCalls).toEqual(['/api/accounts/oauth/active'])
    expect(window.location.hash).toBe('')
  })

  it('renders default 30s placeholder when mail_fetch_timeout_seconds is unset', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') return json({ groups: [] })
      if (u === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    const genBtn = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes('通用')) || null
    await click(genBtn)

    await waitFor(() => {
      const timeoutInput = container.querySelector('#settings-timeout') as HTMLInputElement
      expect(timeoutInput).not.toBeNull()
      expect(timeoutInput.placeholder).toBe('30')
      expect(timeoutInput.value).toBe('')
      expect(container.textContent).toContain('默认 30 秒')
    })
  })

  it('renders logout button and calls logout API on click', async () => {
    const assignMock = vi.fn()
    const target = Object.assign(new EventTarget(), { location: { assign: assignMock } })
    const unauthorized = vi.fn()
    target.addEventListener(UNAUTHORIZED_EVENT, unauthorized)
    vi.stubGlobal('window', target)

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
      expect(unauthorized).toHaveBeenCalledTimes(1)
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
    await click([...container.querySelectorAll('button')].find(b => b.textContent === '分组管理') || null)
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
    await click([...settings.querySelectorAll('button')].find(b => b.textContent === '分组管理') || null)
    const input = settings.querySelector('input[placeholder="新分组名"]') as HTMLInputElement
    const createButton = [...settings.querySelectorAll('button')].find((button) => button.textContent === '创建') || null

    await typeInto(input, '由设置创建')
    await click(createButton)
    await waitFor(() => expect(sidebar.textContent).toContain('由设置创建'))
    await waitFor(() => expect(sidebar.querySelector('.tree-group-block[data-group-id="created-group"] .tree-group-heading')?.getAttribute('draggable')).toBe('true'))

    await click([...settings.querySelectorAll('button')].find(b => b.textContent === '账户管理') || null)
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
    await click([...settings.querySelectorAll('button')].find(b => b.textContent === '分组管理') || null)
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
    await waitFor(() => expect([...settings.querySelectorAll('button')].find(b => b.textContent?.includes('添加账户'))?.disabled).toBe(false))
    await click([...settings.querySelectorAll('button')].find(b => b.textContent?.includes('添加账户')) || null)
    await typeInto(settings.querySelector('#account-email'), 'added@example.test')
    await typeInto(settings.querySelector('#account-imap-host'), 'imap.example.test')
    await typeInto(settings.querySelector('#account-password'), 'test-app-password')
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
      if (u.startsWith('/api/accounts/sync-all')) return json({ target_count: 7, mode: 'full', trigger: 'manual', state: 'queued' })
      if (u.startsWith('/api/accounts')) return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (u === '/api/groups') return json({ groups: [] })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    const syncBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === '同步全部账户') || null
    await waitFor(() => expect(syncBtn?.disabled).toBe(false))
    await click(syncBtn)

    await waitFor(() => {
      expect(container.textContent).toContain('已排队 7 个全量同步任务')
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
    await click([...container.querySelectorAll('button')].find(b => b.textContent === '分组管理') || null)
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

  it('filters accounts by domain and applies bulk actions to the combined filtered selection', async () => {
    const groups = [{ id: 'work', name: '工作', color: null, account_count: 4, sort_order: 0 }]
    const accounts = [
      { id: 'gmail', email: 'ada@gmail.com', status: 'active', sync_status: 'idle', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: 'work', group_name: '工作' },
      { id: 'qq-work-1', email: 'bob@qq.com', status: 'active', sync_status: 'failed', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: 'work', group_name: '工作' },
      { id: 'qq-home', email: 'carol@qq.com', status: 'active', sync_status: 'failed', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: null, group_name: null },
      { id: 'qq-work-2', email: 'ellen@qq.com', status: 'active', sync_status: 'failed', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: 'work', group_name: '工作' },
      { id: '163-work', email: 'dave@163.com', status: 'active', sync_status: 'failed', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: 'work', group_name: '工作' },
    ]
    const updates: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts' && (init.method || 'GET') === 'GET') return json({ accounts, total: accounts.length, limit: 200, offset: 0, has_more: false })
      if (url.pathname.startsWith('/api/accounts/') && init.method === 'PATCH') {
        updates.push(url.pathname.split('/').at(-1) || '')
        return json(accounts.find(account => account.id === updates.at(-1)))
      }
      if (url.pathname === '/api/groups') return json({ groups })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelectorAll('.settings-account-row')).toHaveLength(5))
    const domainSelect = container.querySelector('select[aria-label="按邮箱域名筛选"]') as HTMLSelectElement
    expect([...domainSelect.options].map(option => option.value)).toEqual(['all', '163.com', 'gmail.com', 'qq.com'])

    await changeSelect(domainSelect, 'gmail.com')
    expect([...container.querySelectorAll('.settings-account-identity strong')].map(node => node.textContent)).toEqual(['ada@gmail.com'])

    await changeSelect(domainSelect, 'qq.com')
    await changeSelect(container.querySelector('select[aria-label="按分组筛选"]'), 'work')
    await changeSelect(container.querySelector('select[aria-label="按同步状态筛选"]'), 'failed')
    await typeInto(container.querySelector('input[aria-label="搜索账户"]'), 'qq.com')
    expect([...container.querySelectorAll('.settings-account-identity strong')].map(node => node.textContent)).toEqual(['bob@qq.com', 'ellen@qq.com'])

    await click(container.querySelector('input[aria-label="选择当前筛选的全部账户"]'))
    expect(container.textContent).toContain('已选 2 个账户')
    await click([...container.querySelectorAll('button')].find(button => button.textContent === '暂停同步') || null)
    await waitFor(() => expect(updates.sort()).toEqual(['qq-work-1', 'qq-work-2']))
  })

  it('copies a settings account address without triggering account actions', async () => {
    const account = {
      id: 'copy-account', email: 'copy@example.test', status: 'active', sync_status: 'idle', sync_enabled: true,
      account_type: 'imap', provider: 'imap', group_id: null, group_name: null,
    }
    const calls: Array<{ method: string; url: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push({ method: init.method || 'GET', url: url.pathname })
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts') return json({ accounts: [account], total: 1, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/settings') return json({ settings: settingsResponse })
      return json({ detail: 'unexpected' }, 404)
    }))
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('.settings-account-row')).not.toBeNull())
    await click(container.querySelector('.settings-account-row button[aria-label="复制邮箱地址 copy@example.test"]'))

    expect(writeText).toHaveBeenCalledWith('copy@example.test')
    await waitFor(() => expect(document.body.querySelector('[role="status"]')?.textContent).toBe('已复制地址'))
    expect(calls.some((call) => call.method === 'PATCH')).toBe(false)
  })

  it('opens the edit dialog and saves connection settings, credentials, and group through PATCH', async () => {
    const groups = [
      { id: 'work', name: '工作', color: null, account_count: 1, sort_order: 0 },
      { id: 'personal', name: '个人', color: null, account_count: 0, sort_order: 1 },
    ]
    const account = {
      id: 'account-edit', email: 'edit@example.test', status: 'active', sync_status: 'idle', sync_enabled: true,
      account_type: 'imap', provider: 'imap', group_id: 'work', group_name: '工作',
      imap_config: { imap_host: 'imap.old.test', imap_port: 993, use_ssl: true },
    }
    let currentAccount = { ...account }
    const patches: Array<{ path: string; body: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init.method || 'GET'
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts' && method === 'GET') return json({ accounts: [currentAccount], total: 1, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/accounts/account-edit' && method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as { config?: Record<string, unknown>; group_id?: string; clear_group?: boolean; credentials?: Record<string, unknown> }
        patches.push({ path: url.pathname, body })
        currentAccount = {
          ...currentAccount,
          group_id: body.group_id || currentAccount.group_id,
          group_name: groups.find(group => group.id === (body.group_id || currentAccount.group_id))?.name || currentAccount.group_name,
          imap_config: { ...currentAccount.imap_config, ...body.config },
        }
        return json(currentAccount)
      }
      if (url.pathname === '/api/groups') return json({ groups })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('.settings-account-row')).not.toBeNull())
    const actions = container.querySelector('.settings-row-actions') as HTMLElement
    expect(actions.querySelectorAll('button')[0].getAttribute('aria-label')).toBe('编辑账户 edit@example.test')
    expect(actions.querySelectorAll('button')[1].getAttribute('aria-label')).toBe('同步 edit@example.test')
    await click(actions.querySelector('button[aria-label="编辑账户 edit@example.test"]'))

    const dialog = container.querySelector('dialog') as HTMLDialogElement
    expect(dialog.querySelector('h2')?.textContent).toBe('编辑账户')
    expect((dialog.querySelector('#account-imap-host') as HTMLInputElement).value).toBe('imap.old.test')
    expect((dialog.querySelector('#account-imap-port') as HTMLInputElement).value).toBe('993')
    expect((dialog.querySelector('#account-group') as HTMLSelectElement).value).toBe('work')

    await typeInto(dialog.querySelector('#account-imap-host'), 'imap.new.test')
    await typeInto(dialog.querySelector('#account-imap-port'), '143')
    await click(dialog.querySelector('#account-imap-ssl'))
    await typeInto(dialog.querySelector('#account-password'), 'new-app-password')
    await changeSelect(dialog.querySelector('#account-group'), 'personal')
    await click(dialog.querySelector('button[type="submit"]'))

    await waitFor(() => expect(patches).toEqual([{
      path: '/api/accounts/account-edit',
      body: {
        config: { imap_host: 'imap.new.test', imap_port: 143, use_ssl: false },
        group_id: 'personal',
        credentials: { password: 'new-app-password' },
      },
    }]))
    await waitFor(() => expect(container.querySelector('dialog')).toBeNull())
    await waitFor(() => expect(container.textContent).toContain('账户设置已更新'))
  })

  it('clears an optional OAuth secret only through the explicit clear list', async () => {
    const account = {
      id: 'account-clear-secret', email: 'oauth@example.test', status: 'active', sync_status: 'idle', sync_enabled: true,
      account_type: 'graph', provider: 'graph', group_id: null, group_name: null,
      oauth_client_type: 'public', oauth_tenant: 'common', provider_profile: 'microsoft', imap_config: null,
    }
    const currentAccount = { ...account }
    const patches: Array<{ body: unknown }> = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init.method || 'GET'
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts' && method === 'GET') return json({ accounts: [currentAccount], total: 1, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/accounts/account-clear-secret' && method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as { clear_credentials?: string[] }
        patches.push({ body })
        return json(currentAccount)
      }
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/settings') return json({ settings: settingsResponse })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('.settings-account-row')).not.toBeNull())
    await click(container.querySelector('button[aria-label="编辑账户 oauth@example.test"]'))

    const dialog = container.querySelector('dialog') as HTMLDialogElement
    await click(dialog.querySelector('#account-clear-client-secret'))
    await click(dialog.querySelector('button[type="submit"]'))

    await waitFor(() => expect(patches).toEqual([{ body: { clear_credentials: ['client_secret'] } }]))
    await waitFor(() => expect(container.querySelector('dialog')).toBeNull())
  })

  it('p054: integrates stats, actions and filters into a single first row directly above the account list', async () => {
    const groups = [{ id: 'work', name: '工作', color: null, account_count: 1, sort_order: 0 }]
    const accounts = [
      { id: 'a-gmail', email: 'ada@gmail.com', status: 'active', sync_status: 'idle', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: 'work', group_name: '工作' },
      { id: 'a-qq-enabled', email: 'bob@qq.com', status: 'active', sync_status: 'idle', sync_enabled: true, account_type: 'imap', provider: 'imap', group_id: null, group_name: null },
      { id: 'a-qq-paused', email: 'carol@qq.com', status: 'active', sync_status: 'idle', sync_enabled: false, account_type: 'imap', provider: 'imap', group_id: null, group_name: null },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts') return json({ accounts, total: accounts.length, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelectorAll('.settings-account-row')).toHaveLength(3))

    // The subtitle under the account-management title is gone.
    expect(container.textContent).not.toContain('管理邮箱连接、同步状态与所属分组。')

    // A single first row holds stats, actions, search and the three filters.
    const firstRow = container.querySelector('.settings-accounts-first-row')
    expect(firstRow).not.toBeNull()
    const summaryText = () => [...(firstRow?.querySelectorAll('.settings-summary > span') || [])].map(node => node.textContent)
    expect(summaryText()).toEqual(['账户总数 3', '已显示 3', '已同步 2', '已暂停同步 1'])
    expect([...(firstRow?.querySelectorAll('button') || [])].map(button => button.textContent)).toEqual(
      expect.arrayContaining(['添加账户', '同步全部账户']),
    )
    expect(firstRow?.querySelector('input[aria-label="搜索账户"]')).not.toBeNull()
    expect(firstRow?.querySelector('select[aria-label="按分组筛选"]')).not.toBeNull()
    expect(firstRow?.querySelector('select[aria-label="按同步状态筛选"]')).not.toBeNull()
    expect(firstRow?.querySelector('select[aria-label="按邮箱域名筛选"]')).not.toBeNull()

    // The old footer bar (count text + bottom-right sync-all) is gone.
    expect(container.querySelector('.settings-list-footer')).toBeNull()
    expect(container.textContent).not.toMatch(/显示 \d+ \/ \d+ 个账户/)

    // The account list directly follows the first row.
    expect(container.querySelector('.settings-account-table')?.previousElementSibling).toBe(firstRow)

    // 已显示 reflects the active search/filter while the totals stay global.
    await typeInto(container.querySelector('input[aria-label="搜索账户"]'), 'gmail')
    await waitFor(() => expect(container.querySelectorAll('.settings-account-row')).toHaveLength(1))
    expect(summaryText()).toEqual(['账户总数 3', '已显示 1', '已同步 2', '已暂停同步 1'])
  })

  it('p054: sync-preference toggle shows no success feedback on success', async () => {
    const account = {
      id: 'toggle-account', email: 'toggle@example.test', status: 'active', sync_status: 'idle', sync_enabled: true,
      account_type: 'imap', provider: 'imap', group_id: null, group_name: null,
    }
    const patches: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts/toggle-account' && init.method === 'PATCH') {
        patches.push(JSON.parse(String(init.body)))
        return json({ ...account, sync_enabled: false })
      }
      if (url.pathname === '/api/accounts') return json({ accounts: [account], total: 1, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('.settings-account-row')).not.toBeNull())
    const toggle = container.querySelector('button[aria-label="暂停同步 toggle@example.test"]') as HTMLButtonElement
    await click(toggle)

    await waitFor(() => expect(patches).toEqual([{ sync_enabled: false }]))
    await waitFor(() => expect(toggle.disabled).toBe(false))
    expect(container.textContent).not.toContain('同步偏好已更新')
    expect(container.querySelector('.settings-feedback')).toBeNull()
  })

  it('p054: sync-preference toggle still reports an error feedback on failure', async () => {
    const account = {
      id: 'toggle-fail-account', email: 'toggle-fail@example.test', status: 'active', sync_status: 'idle', sync_enabled: true,
      account_type: 'imap', provider: 'imap', group_id: null, group_name: null,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts/toggle-fail-account' && init.method === 'PATCH') {
        return json({ detail: '同步开关保存失败' }, 500)
      }
      if (url.pathname === '/api/accounts') return json({ accounts: [account], total: 1, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('.settings-account-row')).not.toBeNull())
    await click(container.querySelector('button[aria-label="暂停同步 toggle-fail@example.test"]'))

    await waitFor(() => expect(container.textContent).toContain('同步开关保存失败'))
    expect(container.querySelector('.settings-feedback.is-error')).not.toBeNull()
    expect(container.textContent).not.toContain('同步偏好已更新')
  })

  it('removes settings-page-head and houses sidebar-toggle inside settings-nav (p049)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = new URL(String(input), 'http://localhost')
      if (url.pathname === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (url.pathname === '/api/accounts') return json({ accounts: [], total: 0, limit: 200, offset: 0, has_more: false })
      if (url.pathname === '/api/groups') return json({ groups: [] })
      if (url.pathname === '/api/settings') return json({ settings: {} })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<SettingsPage />)
    // 1. settings-page-head must NOT exist
    expect(container.querySelector('.settings-page-head')).toBeNull()

    // 2. sidebar-toggle (ST01) must exist inside settings-nav
    const toggle = container.querySelector('.settings-nav button[data-ui="ST01"]')
    expect(toggle).not.toBeNull()

    // 3. (p054 supersedes the p049 close-button expectation) The back/close
    // arrow button at the top of settings-nav is removed.
    expect(container.querySelector('.settings-nav .settings-nav-close')).toBeNull()
    expect(container.querySelector('.settings-nav .settings-nav-back')).toBeNull()
    expect(container.querySelector('button[aria-label="关闭设置"]')).toBeNull()
  })
})
