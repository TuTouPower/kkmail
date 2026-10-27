import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsModal'
import { __resetCsrfForTests } from '../api/client'
import { changeSelect, cleanup, click, render, typeInto, waitFor } from '../test/render'

const initialAccounts = [
  { id: 'one', email: 'one@gmail.com', provider: 'graph', group_id: 'work', group_name: '工作', sync_enabled: true, sync_status: 'auth_failed', status: 'active', account_type: 'graph' },
  { id: 'two', email: 'two@example.com', provider: 'imap', group_id: null, group_name: null, sync_enabled: false, sync_status: 'idle', status: 'disabled', account_type: 'imap' },
]
let accounts = structuredClone(initialAccounts)
let groups = [{ id: 'work', name: '工作', account_count: 1, color: null, sort_order: 0 }]
const writes: Array<{ path: string; body: Record<string, unknown> }> = []
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  vi.stubGlobal('HTMLDialogElement', HTMLDialogElement)
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  accounts = structuredClone(initialAccounts)
  groups = [{ id: 'work', name: '工作', account_count: 1, color: null, sort_order: 0 }]
  writes.length = 0
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const path = new URL(String(input), 'http://localhost').pathname
    const method = init.method || 'GET'
    if (path === '/api/auth/me') return json({ csrf_token: 'tok' })
    if (method === 'GET') {
      if (path === '/api/accounts') return json({ accounts, total: accounts.length, limit: 200, offset: 0, has_more: false })
      if (path === '/api/groups') return json({ groups })
      if (path === '/api/settings') return json({ settings: { app_timezone: 'Asia/Shanghai', mail_fetch_timeout_seconds: '120' } })
    }
    const body = init.body ? JSON.parse(String(init.body)) : {}
    writes.push({ path, body })
    if (path.startsWith('/api/accounts/') && method === 'PATCH') {
      if (path.endsWith('/two') && body.group_id) return json({ detail: '分组写入失败' }, 500)
      accounts = accounts.map(a => path.endsWith(`/${a.id}`) ? { ...a, ...body } : a)
      return json(accounts.find(a => path.endsWith(`/${a.id}`)))
    }
    if (path === '/api/groups/work' && method === 'PATCH') {
      groups = groups.map(g => ({ ...g, name: body.name }))
      return json(groups[0])
    }
    return json({ detail: 'unexpected' }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  __resetCsrfForTests()
})

describe('settings workspace redesign', () => {
  it('filters accounts by text, group and sync preference without confusing enabled with healthy', async () => {
    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.textContent).toContain('one@gmail.com'))
    expect(container.textContent).toContain('认证失败')
    await typeInto(container.querySelector('input[aria-label="搜索账户"]'), 'gmail.com')
    expect(container.textContent).toContain('one@gmail.com')
    expect(container.textContent).not.toContain('two@example.com')
    await typeInto(container.querySelector('input[aria-label="搜索账户"]'), '')
    await changeSelect(container.querySelector('select[aria-label="按分组筛选"]'), 'ungrouped')
    expect(container.textContent).not.toContain('one@gmail.com')
    expect(container.textContent).toContain('two@example.com')
    await changeSelect(container.querySelector('select[aria-label="按分组筛选"]'), 'all')
    await changeSelect(container.querySelector('select[aria-label="按同步状态筛选"]'), 'failed')
    expect(container.textContent).toContain('one@gmail.com')
    expect(container.textContent).not.toContain('two@example.com')
  })

  it('persists sync preference through the authenticated account API', async () => {
    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.querySelector('button[aria-label="暂停同步 one@gmail.com"]')).not.toBeNull())
    await click(container.querySelector('button[aria-label="暂停同步 one@gmail.com"]'))
    await waitFor(() => expect(writes).toContainEqual({ path: '/api/accounts/one', body: { sync_enabled: false } }))
    await waitFor(() => expect(container.querySelector('button[aria-label="启用同步 one@gmail.com"]')).not.toBeNull())
  })

  it('reports partial bulk failures and keeps only failed accounts selected for retry', async () => {
    const { container } = await render(<SettingsPage />)
    await waitFor(() => expect(container.textContent).toContain('two@example.com'))
    await click(container.querySelector('input[aria-label="选择当前筛选的全部账户"]'))
    await changeSelect(container.querySelector('select[aria-label="批量移动分组"]'), 'work')
    await click([...container.querySelectorAll('button')].find(b => b.textContent === '移动分组') || null)
    await waitFor(() => expect(container.textContent).toContain('1 个成功，1 个失败'))
    expect((container.querySelector('input[aria-label="选择 one@gmail.com"]') as HTMLInputElement).checked).toBe(false)
    expect((container.querySelector('input[aria-label="选择 two@example.com"]') as HTMLInputElement).checked).toBe(true)
    expect(container.textContent).toContain('two@example.com：分组写入失败')
  })

  it('renames groups in their own section and retains general drafts across query refresh', async () => {
    const { container } = await render(<SettingsPage />)
    await click([...container.querySelectorAll('button')].find(b => b.textContent === '分组管理') || null)
    await waitFor(() => expect(container.querySelector('button[aria-label="重命名 工作"]')).not.toBeNull())
    await click(container.querySelector('button[aria-label="重命名 工作"]'))
    await typeInto(container.querySelector('input[aria-label="分组名称"]'), '项目')
    await click([...container.querySelectorAll('button')].find(b => b.textContent === '保存名称') || null)
    await waitFor(() => expect(writes).toContainEqual({ path: '/api/groups/work', body: { name: '项目' } }))
    await click([...container.querySelectorAll('button')].find(b => b.textContent === '通用') || null)
    await waitFor(() => expect((container.querySelector('#settings-timezone') as HTMLInputElement)?.value).toBe('Asia/Shanghai'))
    await typeInto(container.querySelector('#settings-timezone'), 'UTC')
    const { queryClient, queryKeys } = await import('../api/queries')
    const { act } = await import('react')
    await act(async () => { await queryClient.invalidateQueries({ queryKey: queryKeys.settings }) })
    expect((container.querySelector('#settings-timezone') as HTMLInputElement).value).toBe('UTC')
  })
})
