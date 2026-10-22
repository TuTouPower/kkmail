// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsModal'
import { __resetCsrfForTests } from '../api/client'
import { queryClient } from '../api/queries'
import { cleanup, click, render, typeInto, waitFor } from '../test/render'

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
  __resetCsrfForTests()
  queryClient.clear()
})

describe('<SettingsModal />', () => {
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
})
