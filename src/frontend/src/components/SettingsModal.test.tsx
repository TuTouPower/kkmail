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
})
