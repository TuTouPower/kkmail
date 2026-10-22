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

  // 旧测试 "falls back to per-account folder stats when /api/mail/stats fails"（基于已废弃的 /api/accounts/:id/folders 轮询）已删除：
  // A23 演进为移除失效的 /api/accounts/:id/folders，统一直接调用 /api/mail/accounts/:id/folder-stats
  it('falls back to /api/mail/accounts/:id/folder-stats when global stats fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/groups')) return json({ groups: [] })
      if (u.startsWith('/api/accounts')) {
        return json({
          accounts: [
            { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          ],
          total: 1, limit: 200, offset: 0, has_more: false,
        })
      }
      if (u.startsWith('/api/mail/accounts/acc-1/folder-stats')) {
        return json({
          account_id: 'acc-1',
          folders: [{ role: 'inbox', unread_count: 4, total_count: 8 }],
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

  it('shows unknown dash badge when account stats request fails, without showing pseudo-exact zero (A19)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/groups')) return json({ groups: [] })
      if (u.startsWith('/api/accounts')) {
        return json({
          accounts: [
            { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
            { id: 'acc-2', email: 'b@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          ],
          total: 2, limit: 200, offset: 0, has_more: false,
        })
      }
      // Global stats fails -> fallback to per-account
      if (u.startsWith('/api/mail/stats')) {
        return json({ detail: 'stats failed' }, 500)
      }
      // acc-1 succeeds with 3 unread
      if (u.startsWith('/api/mail/accounts/acc-1/folder-stats')) {
        return json({
          account_id: 'acc-1',
          folders: [{ role: 'inbox', unread_count: 3, total_count: 5 }],
        })
      }
      // acc-2 fails
      if (u.startsWith('/api/mail/accounts/acc-2/folder-stats')) {
        return json({ detail: 'network error' }, 500)
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<Sidebar />)
    await waitFor(() => {
      const unknownBadges = [...container.querySelectorAll('.unread-badge-unknown')]
      expect(unknownBadges.length).toBeGreaterThanOrEqual(1)
      expect(unknownBadges[0].textContent?.trim()).toBe('-')
    })

    // Total unread must NOT display pseudo-exact 3 or 0; it must display '-'
    const totalBadge = container.querySelector('.category-btn .unread-badge')
    expect(totalBadge?.textContent?.trim()).toBe('-')
  })

  // 旧测试 "renders favorites tree with inbox, unread, and sent collapsible entries" 已由 t008 规范升级替代：
  // t008 AC-001 将收藏入口扩充为“所有收件”“所有未读”“已发邮件”“草稿箱”“废纸篓”“垃圾邮件”六大类目；
  // t008 AC-002 增加账号独立展开真实文件夹树能力。
  it('renders 6 favorite categories and account folder trees (t008 AC-001, AC-002)', async () => {
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
      if (u.startsWith('/api/mail/accounts/acc-1/folder-stats')) {
        return json({
          account_id: 'acc-1',
          folders: [
            { folder_id: 'f-inbox', remote_id: 'INBOX', name: 'INBOX', role: 'inbox', unread_count: 2, total_count: 10, parent_remote_id: null },
            { folder_id: 'f-sent', remote_id: 'Sent', name: 'Sent', role: 'sent', unread_count: 0, total_count: 5, parent_remote_id: null },
            { folder_id: 'f-drafts', remote_id: 'Drafts', name: 'Drafts', role: 'drafts', unread_count: 0, total_count: 1, parent_remote_id: null },
            { folder_id: 'f-parent', remote_id: 'Work', name: 'Work', role: 'other', unread_count: 0, total_count: 0, parent_remote_id: null },
            { folder_id: 'f-child', remote_id: 'Work/P1', name: 'P1', role: 'other', unread_count: 0, total_count: 0, parent_remote_id: 'Work' },
          ],
        })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<Sidebar />)
    await waitFor(() => {
      expect(container.textContent).toContain('所有收件')
      expect(container.textContent).toContain('所有未读')
      expect(container.textContent).toContain('已发邮件')
      expect(container.textContent).toContain('草稿箱')
      expect(container.textContent).toContain('废纸篓')
      expect(container.textContent).toContain('垃圾邮件')
    })

    // AC-001: "所有收件" badge has 5; when expanded, acc-1 shows 2, acc-2 shows nothing
    const inboxRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('所有收件'))
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

    // AC-001: Other favorite entries have no badges
    const unreadRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('所有未读'))
    const sentRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('已发邮件'))
    const draftsRow = [...container.querySelectorAll('.favorite-category')].find((el) => el.textContent?.includes('草稿箱'))
    expect(unreadRow?.querySelector('.unread-badge')).toBeNull()
    expect(sentRow?.querySelector('.unread-badge')).toBeNull()
    expect(draftsRow?.querySelector('.unread-badge')).toBeNull()

    // AC-001: Clicking top-level switches view
    await fireClick(draftsRow?.querySelector('.category-btn') as HTMLElement)
    expect(useMailStore.getState().view).toEqual({ type: 'favorite', category: 'drafts' })

    // AC-002: Account folder tree expansion
    const acc1Row = [...container.querySelectorAll('.account-row')].find((el) => el.textContent?.includes('a@x.test'))
    expect(acc1Row).toBeDefined()
    const acc1FolderToggle = acc1Row?.querySelector('.account-folders-toggle') as HTMLElement
    expect(acc1FolderToggle).not.toBeNull()
    await fireClick(acc1FolderToggle)

    await waitFor(() => {
      // Standard roles translated and displayed
      expect(acc1Row?.textContent).toContain('收件箱')
      expect(acc1Row?.textContent).toContain('已发送')
      expect(acc1Row?.textContent).toContain('草稿箱')
      // Custom folders displayed
      expect(acc1Row?.textContent).toContain('Work')
      expect(acc1Row?.textContent).toContain('P1')
    })

    // Click on custom folder switches to folder view
    const p1Btn = [...acc1Row!.querySelectorAll('.folder-item-btn')].find((el) => el.textContent?.includes('P1')) as HTMLElement
    expect(p1Btn).toBeDefined()
    await fireClick(p1Btn)
    expect(useMailStore.getState().view).toEqual({
      type: 'folder',
      accountId: 'acc-1',
      email: 'a@x.test',
      folderId: 'f-child',
      folderName: 'P1',
      folderRole: 'other',
    })
  })

  it('renders real error message and refetch retry button on accounts error (AC-003, AC-004)', async () => {
    let shouldFail = true
    let accountsCalls = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/groups')) return json({ groups: [] })
      if (u.startsWith('/api/accounts')) {
        accountsCalls++
        if (shouldFail) {
          return json({ detail: 'Internal Server Error: DB connection failed' }, 500)
        }
        return json({
          accounts: [
            { id: 'acc-1', email: 'recovered@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          ],
          total: 1, limit: 200, offset: 0, has_more: false,
        })
      }
      if (u.startsWith('/api/mail/stats')) return json({ total_unread: 0, accounts: [] })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<Sidebar />)

    await waitFor(() => {
      expect(container.textContent).not.toContain('请确认已登录且后端可用')
      expect(container.textContent).toContain('DB connection failed')
    }, 3000)

    const retryBtn = container.querySelector('.account-error-retry') as HTMLButtonElement | null
    expect(retryBtn).not.toBeNull()

    shouldFail = false
    const { click: fireClick } = await import('../test/render')
    await fireClick(retryBtn!)

    await waitFor(() => {
      expect(accountsCalls).toBeGreaterThanOrEqual(2)
      expect(container.textContent).toContain('recovered@x.test')
    })
  })
})
