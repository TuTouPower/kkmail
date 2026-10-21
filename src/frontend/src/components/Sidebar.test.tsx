// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Sidebar from './Sidebar'
import { useMailStore } from '../store/mailStore'
import { __resetCsrfForTests } from '../api/client'
import { cleanup, render, waitFor } from '../test/render'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('<Sidebar />', () => {
  beforeEach(() => {
    useMailStore.setState({ view: { type: 'allInbox' }, listFilter: 'all' })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    __resetCsrfForTests()
  })

  it('renders unread counts from global /api/mail/stats', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      calls.push(u)
      if (u.startsWith('/api/groups')) return json({ groups: [] })
      if (u.startsWith('/api/accounts')) return json({
        accounts: [
          { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          { id: 'acc-2', email: 'b@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
        ],
        total: 2, limit: 200, offset: 0, has_more: false,
      })
      if (u.startsWith('/api/mail/stats')) {
        return json({
          total_unread: 5,
          accounts: [
            { account_id: 'acc-1', unread_count: 2, total_count: 10 },
            { account_id: 'acc-2', unread_count: 3, total_count: 20 },
          ],
        })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<Sidebar />)
    await waitFor(() => {
      const badges = [...container.querySelectorAll('.unread-badge')].map((el) => el.textContent)
      expect(badges).toContain('5')
      expect(badges).toContain('2')
      expect(badges).toContain('3')
    })
    expect(calls.some((u) => u.startsWith('/api/mail/stats'))).toBe(true)
  })

  it('falls back to per-account folder stats when /api/mail/stats fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/groups')) return json({ groups: [] })
      if (u.startsWith('/api/accounts')) {
        if (u.includes('/folders')) {
          if (u.includes('acc-1')) return json([{ role: 'inbox', unread_count: 4, total_count: 8 }])
          return json([{ role: 'inbox', unread_count: 1, total_count: 2 }])
        }
        return json({
          accounts: [
            { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          ],
          total: 1, limit: 200, offset: 0, has_more: false,
        })
      }
      if (u.startsWith('/api/mail/stats')) {
        return json({ detail: 'not found' }, 404)
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<Sidebar />)
    await waitFor(() => {
      const badges = [...container.querySelectorAll('.unread-badge')].map((el) => el.textContent)
      expect(badges).toContain('4')
    })
  })
})
