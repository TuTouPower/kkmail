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

  it('renders favorites tree with inbox, unread, and sent collapsible entries (AC-001 ~ AC-004)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
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
            { account_id: 'acc-2', unread_count: 0, total_count: 20 },
          ],
        })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<Sidebar />)
    await waitFor(() => {
      expect(container.textContent).toContain('所有收件箱')
      expect(container.textContent).toContain('所有未读')
      expect(container.textContent).toContain('所有已发邮件')
    })

    // AC-001: Three collapsible entries exist
    const favoriteSection = container.querySelector('.side-section')
    expect(favoriteSection).not.toBeNull()

    // AC-002: "所有收件箱" badge has 5; when expanded, acc-1 shows 2, acc-2 shows nothing
    const inboxRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('所有收件箱'))
    expect(inboxRow).toBeDefined()
    await waitFor(() => {
      expect(inboxRow?.querySelector('.unread-badge')?.textContent).toBe('5')
    })

    // Click toggle to expand inbox
    const inboxToggle = inboxRow?.querySelector('.category-toggle')
    expect(inboxToggle).not.toBeNull()
    const { click: fireClick } = await import('../test/render')
    await fireClick(inboxToggle as HTMLElement)

    await waitFor(() => {
      expect(container.textContent).toContain('a@x.test')
      expect(container.textContent).toContain('b@x.test')
    })
    const acc1Inbox = [...container.querySelectorAll('.favorite-account-row')].find((el) => el.textContent?.includes('a@x.test'))
    const acc2Inbox = [...container.querySelectorAll('.favorite-account-row')].find((el) => el.textContent?.includes('b@x.test'))
    expect(acc1Inbox?.querySelector('.unread-badge')?.textContent).toBe('2')
    expect(acc2Inbox?.querySelector('.unread-badge')).toBeNull()

    // AC-003: "所有未读" and "所有已发邮件" have no badges on parent or accounts
    const unreadRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('所有未读'))
    const sentRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('所有已发邮件'))
    expect(unreadRow?.querySelector('.unread-badge')).toBeNull()
    expect(sentRow?.querySelector('.unread-badge')).toBeNull()

    // Expand unread & sent
    await fireClick(unreadRow?.querySelector('.category-toggle') as HTMLElement)
    await fireClick(sentRow?.querySelector('.category-toggle') as HTMLElement)
    const unreadAndSentRows = [...container.querySelectorAll('.favorite-account-row')].filter((el) =>
      el.closest('.favorite-category-unread') || el.closest('.favorite-category-sent'),
    )
    for (const r of unreadAndSentRows) {
      expect(r.querySelector('.unread-badge')).toBeNull()
    }

    // AC-004: Clicking top-level switches view; clicking account switches view
    await fireClick(sentRow?.querySelector('.category-btn') as HTMLElement)
    expect(useMailStore.getState().view).toEqual({ type: 'favorite', category: 'sent' })

    await fireClick(acc1Inbox?.querySelector('.category-account-btn') as HTMLElement)
    expect(useMailStore.getState().view).toEqual({ type: 'favorite', category: 'inbox', accountId: 'acc-1', email: 'a@x.test' })
  })
})
