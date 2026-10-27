// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MessageList from './MessageList'
import { useMailStore } from '../store/mailStore'
import { __resetCsrfForTests } from '../api/client'
import * as queryApi from '../api/queries'
import { cleanup, click, render, typeInto, waitFor } from '../test/render'

let intersectionCallback: IntersectionObserverCallback | null = null
let intersectionObservers: MockIntersectionObserver[] = []

class MockIntersectionObserver {
  callback: IntersectionObserverCallback
  constructor(cb: IntersectionObserverCallback) {
    this.callback = cb
    intersectionCallback = cb
    intersectionObservers.push(this)
  }
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

const row = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  account_id: 'acc-1',
  account_email: 'box@x.test',
  subject: `Subject ${id}`,
  from_address: `${id}@sender.test`,
  from_name: `Sender ${id}`,
  sort_time: '2026-10-20T08:00:00Z',
  is_read: false,
  is_flagged: false,
  has_attachments: false,
  snippet: `snippet ${id}`,
  folder_id: 'f1',
  locations: [{ folder_id: 'f1', role: 'inbox' }],
  ...over,
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

let calls: string[] = []

beforeEach(() => {
  calls = []
  intersectionCallback = null
  intersectionObservers = []
  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
  useMailStore.setState({ view: { type: 'allInbox' }, listFilter: 'all', search: '', selectedIds: [], selectedKey: null })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const u = String(url)
    calls.push(u)
    if (u.startsWith('/api/accounts')) return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
    if (u.includes('/folder-stats')) return json({ folders: [{ role: 'inbox', unread_count: 1, total_count: 2 }] })
    if (u.startsWith('/api/mail/inbox')) return json({ items: [row('a'), row('b', { is_flagged: true, is_read: true })], next_cursor: null })
    if (u.startsWith('/api/mail/search')) {
      const urlObj = new URL(u, 'http://localhost')
      const q = urlObj.searchParams.get('q') || ''
      const offset = Number(urlObj.searchParams.get('offset') || '0')
      if (q === 'page-test') {
        if (offset === 0) {
          return json({ query: q, items: [row('p1')], total: 2, offset: 0, next_offset: 1 })
        }
        return json({ query: q, items: [row('p2')], total: 2, offset: 1, next_offset: null })
      }
      return json({ query: q, items: [row('s')], total: 1, offset: 0, next_offset: null })
    }
    if (u.includes('/folder-stats')) {
      return json({ folders: [{ folder_id: 'f1', role: 'inbox', total_count: 2, unread_count: 1 }] })
    }
    return json({ detail: 'unexpected' }, 404)
  }))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

const subjects = (c: HTMLElement) => [...c.querySelectorAll('.subject')].map((n) => n.textContent)

describe('<MessageList />', () => {
  it('renders the unified inbox from mail-core', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject a', 'Subject b']))
    expect(container.querySelector('.list-count')?.textContent).toContain('2 封邮件 · 1 封未读')
    expect(calls.some((u) => u.startsWith('/api/mail/inbox?limit=100'))).toBe(true)
  })

  it('windows long message lists and follows scroll position', async () => {
    const originalFetch = vi.mocked(fetch)
    const items = Array.from({ length: 2000 }, (_, index) => row(`many-${index}`))
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).startsWith('/api/mail/inbox')) {
        return json({ items, next_cursor: null })
      }
      return originalFetch(url, init)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container).length).toBeGreaterThan(0))
    expect(container.querySelectorAll('.message-row').length).toBeLessThan(40)
    expect(subjects(container)[0]).toBe('Subject many-0')
    const firstRow = container.querySelector('.message-row') as HTMLElement
    expect(firstRow.style.width).toBe('100%')
    expect(firstRow.style.flex).toBe('0 0 auto')
    expect(firstRow.style.height).toBe('96px')
    expect(firstRow.parentElement?.style.height).toBe('100px')

    const list = container.querySelector('.message-list') as HTMLDivElement
    Object.defineProperty(list, 'clientHeight', { configurable: true, value: 500 })
    Object.defineProperty(list, 'scrollHeight', { configurable: true, value: 200_000 })
    list.scrollTop = 100 * 40
    const { act } = await import('react')
    await act(async () => list.dispatchEvent(new Event('scroll', { bubbles: true })))

    await waitFor(() => expect(subjects(container)[0]).toBe('Subject many-32'))
    expect(container.querySelectorAll('.message-row').length).toBeLessThan(40)
  })

  it('coalesces rapid scroll events into a single rAF-throttled window update (F4)', async () => {
    const originalFetch = vi.mocked(fetch)
    const items = Array.from({ length: 2000 }, (_, index) => row(`many-${index}`))
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).startsWith('/api/mail/inbox')) {
        return json({ items, next_cursor: null })
      }
      return originalFetch(url, init)
    }))
    let rafSeq = 0
    const pendingFrames = new Map<number, (time: number) => void>()
    vi.stubGlobal('requestAnimationFrame', (cb: (time: number) => void) => {
      rafSeq += 1
      pendingFrames.set(rafSeq, cb)
      return rafSeq
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => { pendingFrames.delete(id) })

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container).length).toBeGreaterThan(0))
    expect(subjects(container)[0]).toBe('Subject many-0')

    const list = container.querySelector('.message-list') as HTMLDivElement
    Object.defineProperty(list, 'clientHeight', { configurable: true, value: 500 })
    Object.defineProperty(list, 'scrollHeight', { configurable: true, value: 200_000 })
    const { act } = await import('react')
    for (const top of [40 * 40, 80 * 40, 100 * 40]) {
      list.scrollTop = top
      await act(async () => list.dispatchEvent(new Event('scroll', { bubbles: true })))
    }
    // No animation frame has run: the window must not have moved, and
    // the three events coalesced into exactly one pending frame.
    expect(subjects(container)[0]).toBe('Subject many-0')
    expect(pendingFrames.size).toBe(1)

    const [frame] = [...pendingFrames.values()]
    await act(async () => frame(0))
    await waitFor(() => expect(subjects(container)[0]).toBe('Subject many-32'))
  })

  it('flagged filter uses the server-side is_flagged field', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    await click([...container.querySelectorAll('[role=tab]')].find((b) => b.textContent === '已标记') || null)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject b']))
  })

  it('switches to server search once the query is long enough', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    await typeInto(container.querySelector('input[name=search]'), 'zz')
    await waitFor(() => expect(subjects(container)).toEqual(['Subject s']))
    expect(calls.some((u) => u.startsWith('/api/mail/search?q=zz'))).toBe(true)
  })

  it('keeps server search scoped to the selected real folder', async () => {
    useMailStore.setState({
      view: { type: 'folder', accountId: 'acc-1', email: 'box@x.test', folderId: 'folder-1', folderName: 'INBOX', folderRole: 'inbox' },
      search: 'invoice',
    })
    await render(<MessageList />)
    await waitFor(() => expect(calls.some((url) => url.startsWith('/api/mail/search?') && url.includes('folder_id=folder-1'))).toBe(true))
  })

  it('CJK query triggers search immediately without debounce delay, and clear is instant', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement

    // CJK character triggers search immediately
    await typeInto(input, '测')
    await waitFor(() => expect(useMailStore.getState().search).toBe('测'))
    expect(calls.some((u) => u.includes('/api/mail/search') && decodeURIComponent(u).includes('q=测'))).toBe(true)

    // Clearing search takes effect immediately
    await typeInto(input, '')
    await waitFor(() => expect(useMailStore.getState().search).toBe(''))
  })

  it('handles IME composition: does not update search until composition ends', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement

    // Simulate IME composition start
    input.dispatchEvent(new Event('compositionstart', { bubbles: true }))
    await typeInto(input, 'zhong')
    // During composition, search should remain empty
    expect(useMailStore.getState().search).toBe('')

    // End composition with Chinese character
    input.value = '中'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '中' }))
    await waitFor(() => expect(useMailStore.getState().search).toBe('中'))
  })

  it('filters by account UUID when an account is selected', async () => {
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-1', email: 'box@x.test' } })
    await render(<MessageList />)
    await waitFor(() => expect(calls.some((u) => u.includes('account_id=acc-1'))).toBe(true))
  })

  it('scopes group inbox, unread, search, and mark-all-read requests to the selected group', async () => {
    useMailStore.setState({ view: { type: 'group', groupId: 'group-1', groupName: '税务归档', category: 'unread' } })
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(calls.some((url) => url.includes('group_id=group-1') && url.includes('is_read=false'))).toBe(true))
    await typeInto(container.querySelector('input[name=search]'), 'scope')
    await waitFor(() => expect(calls.some((url) => url.startsWith('/api/mail/search') && url.includes('group_id=group-1'))).toBe(true))
  })

  it('message rows are keyboard operable (Enter selects)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const row = container.querySelector('.message-row') as HTMLElement
    expect(row.getAttribute('tabindex')).toBe('0')
    expect(row.getAttribute('role')).toBeNull()
    expect(row.getAttribute('aria-selected')).toBeNull()
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await waitFor(() => expect(useMailStore.getState().selectedKey).toBe('a'))
  })

  it('checkbox stops keydown propagation to prevent opening row', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const checkBtn = container.querySelector('.message-check') as HTMLElement
    expect(checkBtn.getAttribute('role')).toBe('checkbox')
    expect(checkBtn.getAttribute('aria-checked')).toBe('false')
    checkBtn.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    checkBtn.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }))
    expect(useMailStore.getState().selectedKey).toBeNull()
  })

  it('triggers search with single CJK character, but requires 2 chars for ascii', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement

    await typeInto(input, 'a')
    expect(calls.some((u) => u.startsWith('/api/mail/search'))).toBe(false)

    await typeInto(input, '信')
    await waitFor(() => expect(calls.some((u) => u.includes('/api/mail/search?q='))).toBe(true))
  })

  // Note: 旧测试 'supports search pagination via next_offset and load more button'
  // 测试了已废弃的手动加载更多按钮 .load-more-btn 与点击交互，因 AC-003/AC-004 升级为触底自动加载而语义失效，
  // 予以移除并由下方 AC-001 ~ AC-005 测试替代。

  it('displays authoritative total count from folder-stats and matches unread count in unread view (AC-001)', async () => {
    const originalFetch = vi.mocked(fetch)
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/folder-stats')) {
        return json({
          account_id: 'acc-1',
          folders: [
            { folder_id: 'f1', role: 'inbox', name: 'INBOX', total_count: 7706, unread_count: 42 },
          ],
        })
      }
      return originalFetch(url)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject a', 'Subject b']))
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('7706 封邮件 · 42 封未读')
    })

    await click([...container.querySelectorAll('[role=tab]')].find((b) => b.textContent === '未读') || null)
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('42 封邮件 · 42 封未读')
    })
  })

  it('shows zero when the selected account has no folder with the target role', async () => {
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-1', email: 'box@x.test' } })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      if (u.includes('/folder-stats')) {
        return json({ folders: [{ folder_id: 'sent-1', role: 'sent', total_count: 91, unread_count: 17 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('0 封邮件 · 0 封未读')
    })
  })

  it('keeps all-account counts unknown until every stats response arrives', async () => {
    let releaseStats: (() => void) | undefined
    const statsGate = new Promise<void>((resolve) => {
      releaseStats = resolve
    })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      calls.push(u)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [
          { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          { id: 'acc-2', email: 'b@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
        ], total: 2, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [row('a'), row('b')], next_cursor: null })
      if (u.includes('/api/mail/accounts/acc-1/folder-stats')) {
        await statsGate
        return json({ folders: [{ folder_id: 'inbox-1', role: 'inbox', total_count: 100, unread_count: 10 }] })
      }
      if (u.includes('/api/mail/accounts/acc-2/folder-stats')) {
        await statsGate
        return json({ folders: [{ folder_id: 'inbox-2', role: 'inbox', total_count: 30, unread_count: 7 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject a', 'Subject b']))
    await waitFor(() => expect(calls.filter((url) => url.includes('/folder-stats'))).toHaveLength(2))
    expect(container.querySelector('.list-count')?.textContent).toBe('— 封邮件 · — 封未读')

    releaseStats?.()
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('130 封邮件 · 17 封未读')
    })
  })

  it('does not present a partial all-account stats result as a complete total', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [
          { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          { id: 'acc-2', email: 'b@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
        ], total: 2, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      if (u.includes('/api/mail/accounts/acc-1/folder-stats')) {
        return json({ folders: [{ folder_id: 'inbox-1', role: 'inbox', total_count: 100, unread_count: 10 }] })
      }
      if (u.includes('/api/mail/accounts/acc-2/folder-stats')) return json({ detail: 'stats unavailable' }, 500)
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('— 封邮件 · — 封未读')
    })
  })

  it('bounds concurrent folder-stats requests in the all-accounts view (A69)', async () => {
    const accountIds = Array.from({ length: 20 }, (_, i) => `acc-${i + 1}`)
    let started = 0
    let active = 0
    let maxActive = 0
    let releaseStats!: () => void
    const statsGate = new Promise<void>((resolve) => { releaseStats = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      calls.push(u)
      if (u.startsWith('/api/accounts')) {
        return json({
          accounts: accountIds.map((id) => ({ id, email: `${id}@x.test`, status: 'active', account_type: 'imap', provider: 'imap', sync_enabled: true })),
          total: accountIds.length, limit: 200, offset: 0, has_more: false,
        })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      if (u.includes('/folder-stats')) {
        started += 1
        active += 1
        maxActive = Math.max(maxActive, active)
        await statsGate
        active -= 1
        return json({ folders: [{ folder_id: 'f1', role: 'inbox', total_count: 1, unread_count: 1 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(started).toBeGreaterThan(0))
    const { act } = await import('react')
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    // With a concurrency pool of 8, only the first wave may be in flight
    // even though 20 enabled accounts need stats.
    expect(started).toBe(8)
    expect(maxActive).toBeLessThanOrEqual(8)

    releaseStats()
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('20 封邮件 · 20 封未读')
    })
    expect(maxActive).toBeLessThanOrEqual(8)
  })

  it('sums all-account stats when every account request succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [
          { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          { id: 'acc-2', email: 'b@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
        ], total: 2, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      if (u.includes('/api/mail/accounts/acc-1/folder-stats')) {
        return json({ folders: [{ folder_id: 'inbox-1', role: 'inbox', total_count: 100, unread_count: 10 }] })
      }
      if (u.includes('/api/mail/accounts/acc-2/folder-stats')) {
        return json({ folders: [{ folder_id: 'inbox-2', role: 'inbox', total_count: 30, unread_count: 7 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('130 封邮件 · 17 封未读')
    })
  })

  it('excludes disabled accounts from the aggregate folder-stats fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      calls.push(u)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [
          { id: 'acc-1', email: 'paused@x.test', status: 'active', sync_enabled: false, account_type: 'imap', provider: 'imap' },
          { id: 'acc-2', email: 'active@x.test', status: 'active', sync_enabled: true, account_type: 'imap', provider: 'imap' },
        ], total: 2, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      if (u.includes('/api/mail/accounts/acc-1/folder-stats')) return json({ detail: 'disabled account must not be queried' }, 500)
      if (u.includes('/api/mail/accounts/acc-2/folder-stats')) {
        return json({ folders: [{ folder_id: 'inbox-2', role: 'inbox', total_count: 5, unread_count: 2 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('5 封邮件 · 2 封未读'))
    expect(calls.some((url) => url.includes('/api/mail/accounts/acc-1/folder-stats'))).toBe(false)
    expect(calls.filter((url) => url.includes('/folder-stats'))).toHaveLength(1)
  })

  it('returns zero aggregate counts when every account is disabled', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      calls.push(u)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [
          { id: 'acc-1', email: 'paused@x.test', status: 'active', sync_enabled: false, account_type: 'imap', provider: 'imap' },
        ], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('0 封邮件 · 0 封未读'))
    expect(calls.some((url) => url.includes('/folder-stats'))).toBe(false)
  })

  it('does not substitute other folders for a missing role in all-account stats', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [
          { id: 'acc-1', email: 'a@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
          { id: 'acc-2', email: 'b@x.test', status: 'active', account_type: 'imap', provider: 'imap' },
        ], total: 2, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [], next_cursor: null })
      if (u.includes('/api/mail/accounts/acc-1/folder-stats')) {
        return json({ folders: [{ folder_id: 'inbox-1', role: 'inbox', total_count: 100, unread_count: 10 }] })
      }
      if (u.includes('/api/mail/accounts/acc-2/folder-stats')) {
        return json({ folders: [{ folder_id: 'sent-2', role: 'sent', total_count: 91, unread_count: 17 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toBe('100 封邮件 · 10 封未读')
    })
  })

  it('displays authoritative matching total count in search mode (AC-002)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement

    await typeInto(input, 'page-test')
    await waitFor(() => expect(subjects(container)).toEqual(['Subject p1']))
    expect(container.querySelector('.list-count')?.textContent).toContain('2 封邮件')
  })

  it('removes load more button and pagination count text (AC-003)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement

    await typeInto(input, 'page-test')
    await waitFor(() => expect(subjects(container)).toEqual(['Subject p1']))

    expect(container.querySelector('.load-more-btn')).toBeNull()
    expect(container.querySelector('[data-ui="ML14"]')).toBeNull()
    expect(container.textContent).not.toContain('已加载 1 封')
  })

  it('automatically triggers next page load on intersection sentinel or scroll (AC-004, AC-005)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement

    await typeInto(input, 'page-test')
    await waitFor(() => expect(subjects(container)).toEqual(['Subject p1']))

    const sentinel = container.querySelector('.list-sentinel')
    expect(sentinel).not.toBeNull()

    const { act } = await import('react')
    await act(async () => {
      if (intersectionCallback) {
        intersectionCallback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
      }
    })

    await waitFor(() => expect(subjects(container)).toEqual(['Subject p1', 'Subject p2']))
    expect(calls.some((u) => u.includes('offset=1'))).toBe(true)

    await waitFor(() => {
      expect(container.querySelector('.list-sentinel')).toBeNull()
      expect(container.textContent).toContain('已加载全部邮件')
    })
  })

  it('does not resubscribe the IntersectionObserver when only the query result identity changes (A126)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const input = container.querySelector('input[name=search]') as HTMLInputElement
    await typeInto(input, 'page-test')
    await waitFor(() => expect(subjects(container)).toEqual(['Subject p1']))
    await waitFor(() => expect(container.querySelector('.list-sentinel')).not.toBeNull())
    const { act } = await import('react')
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    const observerCountBefore = intersectionObservers.length
    expect(observerCountBefore).toBeGreaterThan(0)
    const disconnectsBefore = intersectionObservers.map((o) => vi.mocked(o.disconnect).mock.calls.length)

    // A refetch/settle produces a brand-new infinite-query result object
    // while searching / hasMore / loadingMore and the stable fetchNextPage
    // reference all stay the same. The observer must not churn.
    const key = queryApi.queryKeys.search('page-test', queryApi.accountScope(undefined))
    const data = queryApi.queryClient.getQueryData<{ pages: Array<{ items: Array<{ subject: string }> }>; pageParams: unknown[] }>(key)
    expect(data).toBeDefined()
    await act(async () => {
      queryApi.queryClient.setQueryData(key, {
        // Content genuinely changes (no structural-sharing shortcut) while
        // searching / hasMore / loadingMore stay the same.
        pages: data!.pages.map((p) => ({ ...p, items: p.items.map((it) => ({ ...it, subject: `${it.subject} v2` })) })),
        pageParams: [...data!.pageParams],
      })
    })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })

    expect(intersectionObservers.length).toBe(observerCountBefore)
    expect(intersectionObservers.map((o) => vi.mocked(o.disconnect).mock.calls.length)).toEqual(disconnectsBefore)
  })

  it('requests folder_role=sent when favorite category is sent', async () => {
    useMailStore.setState({ view: { type: 'favorite', category: 'sent' } })
    await render(<MessageList />)
    await waitFor(() => {
      expect(calls.some((u) => u.includes('folder_role=sent'))).toBe(true)
    })
  })

  it('requests folder_role=inbox&is_read=false when favorite category is unread', async () => {
    useMailStore.setState({ view: { type: 'favorite', category: 'unread' } })
    await render(<MessageList />)
    await waitFor(() => {
      expect(calls.some((u) => u.includes('folder_role=inbox') && u.includes('is_read=false'))).toBe(true)
    })
  })

  it('opens context menu on right click with options and handles actions (AC-004, AC-005)', async () => {
    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toHaveLength(2))
    const firstRow = container.querySelector('.message-row') as HTMLElement
    expect(firstRow).not.toBeNull()

    const { act } = await import('react')
    await act(async () => {
      firstRow.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 100, clientY: 150 }))
    })

    await waitFor(() => expect(container.querySelector('.context-menu')).not.toBeNull())
    const menu = container.querySelector('.context-menu')
    expect(menu?.textContent).toContain('打开')
    expect(menu?.textContent).toContain('标为已读')
    expect(menu?.textContent).toContain('标记旗标')
    expect(menu?.textContent).toContain('移到废纸篓')
    expect(menu?.textContent).not.toContain('回复')
    expect(menu?.textContent).not.toContain('转发')

    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    await waitFor(() => expect(container.querySelector('.context-menu')).toBeNull())

    await act(async () => {
      firstRow.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 100, clientY: 150 }))
    })
    await waitFor(() => expect(container.querySelector('.context-menu')).not.toBeNull())
    const flagItem = [...container.querySelectorAll('.context-menu-item')].find((el) => el.textContent?.includes('标记旗标'))
    expect(flagItem).toBeDefined()
    await click(flagItem as HTMLElement)
    await waitFor(() => expect(container.querySelector('.context-menu')).toBeNull())
  })

  it('deduplicates messages with the same id across pages', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/api/mail/inbox')) {
        return json({
          items: [
            { id: 'dup-1', account_id: 'acc-1', subject: 'Unique 1', from_address: 'a@x.test', from_name: 'A', sort_time: '2026-10-21T10:00:00Z', is_read: false, is_flagged: false, has_attachments: false, snippet: '' },
            { id: 'dup-1', account_id: 'acc-1', subject: 'Duplicate 1', from_address: 'a@x.test', from_name: 'A', sort_time: '2026-10-21T10:00:00Z', is_read: false, is_flagged: false, has_attachments: false, snippet: '' },
          ],
          next_cursor: null,
          has_more: false,
        })
      }
      if (u.includes('/folder-stats')) {
        return json({ folders: [{ role: 'inbox', unread_count: 1, total_count: 1 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => {
      const rows = container.querySelectorAll('.message-row')
      expect(rows).toHaveLength(1)
    })
  })

  it('passes sort_order=asc when toggled to oldest first', async () => {
    useMailStore.setState({ sortNewest: false })
    await render(<MessageList />)
    await waitFor(() => {
      expect(calls.some((u) => u.includes('sort_order=asc'))).toBe(true)
    })
  })

  it('displays authoritative unread count from server folder-stats', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) {
        return json({ items: [row('a', { is_read: true })], next_cursor: null })
      }
      if (u.includes('/folder-stats')) {
        return json({ folders: [{ role: 'inbox', unread_count: 42, total_count: 100 }] })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => {
      expect(container.querySelector('.list-count')?.textContent).toContain('42 封未读')
    })
  })

  it('decrements the list unread count immediately when opening an unread message', async () => {
    const originalFetch = vi.mocked(fetch)
    const markRead = vi.spyOn(queryApi, 'markReadOptimistic')
    let resolveRead!: (response: Response) => void
    let readStarted = false
    let readComplete = false
    const readRequest = new Promise<Response>((resolve) => { resolveRead = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/auth/me')) return json({ csrf_token: 'test-csrf' })
      if (String(url).includes('/api/mail/messages/') && String(url).endsWith('/read')) {
        readStarted = true
        await readRequest
        return json({ id: 'a', is_read: true })
      }
      if (String(url).includes('/folder-stats') && readComplete) {
        return json({ folders: [{ folder_id: 'f1', role: 'inbox', unread_count: 0, total_count: 2 }] })
      }
      return originalFetch(url, init)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('2 封邮件 · 1 封未读'))
    await click(container.querySelector('.message-row.unread'))
    expect(useMailStore.getState().selectedKey).not.toBeNull()
    expect(markRead).toHaveBeenCalled()
    await waitFor(() => expect(readStarted).toBe(true))
    await waitFor(() => expect(container.querySelector('.message-row.unread')).toBeNull())
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('2 封邮件 · 0 封未读'))
    readComplete = true
    resolveRead(json({ id: 'a', is_read: true }))
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('2 封邮件 · 0 封未读'))
  })

  it('decrements every matching folder count for a message in multiple same-role folders', async () => {
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-1', email: 'box@x.test' } })
    let resolveRead!: (response: Response) => void
    let readComplete = false
    const readRequest = new Promise<Response>((resolve) => { resolveRead = resolve })
    const originalFetch = vi.mocked(fetch)
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'test-csrf' })
      if (u.includes('/api/mail/messages/') && u.endsWith('/read')) {
        await readRequest
        return json({ is_read: true })
      }
      if (u.startsWith('/api/mail/inbox')) {
        return json({ items: [row('multi', { locations: [
          { folder_id: 'f1', role: 'inbox' },
          { folder_id: 'f2', role: 'inbox' },
        ] })], next_cursor: null })
      }
      if (u.includes('/folder-stats')) {
        return json({ folders: readComplete
          ? [
            { folder_id: 'f1', role: 'inbox', unread_count: 1, total_count: 5 },
            { folder_id: 'f2', role: 'inbox', unread_count: 0, total_count: 4 },
          ]
          : [
            { folder_id: 'f1', role: 'inbox', unread_count: 2, total_count: 5 },
            { folder_id: 'f2', role: 'inbox', unread_count: 1, total_count: 4 },
          ] })
      }
      return originalFetch(url, init)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('9 封邮件 · 3 封未读'))
    await click(container.querySelector('.message-row.unread'))
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('9 封邮件 · 1 封未读'))
    readComplete = true
    resolveRead(json({ is_read: true }))
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('9 封邮件 · 1 封未读'))
  })

  it('shows unknown unread count when folder stats are incomplete', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) return json({ items: [row('a', { is_read: true })], next_cursor: null })
      if (u.includes('/folder-stats')) return json({ folders: [{ role: 'inbox', unread_count: null, total_count: null }] })
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toContain('— 封未读'))
  })

  it('calls POST /api/mail/mark-all-read on mark-all click', async () => {
    let markAllPayload: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) {
        return json({ items: [row('a', { is_read: false })], next_cursor: null })
      }
      if (u.includes('/folder-stats')) {
        return json({ folders: [{ role: 'inbox', unread_count: 1, total_count: 1 }] })
      }
      if (u === '/api/auth/me') {
        return json({ csrf_token: 'fake-token' })
      }
      if (u === '/api/mail/mark-all-read') {
        markAllPayload = JSON.parse(String(init?.body || '{}'))
        return json({ success: true, count: 1 })
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(subjects(container)).toEqual(['Subject a']))

    const markAllBtn = container.querySelector('.mark-all-btn') as HTMLButtonElement
    expect(markAllBtn).not.toBeNull()
    expect(markAllBtn.disabled).toBe(false)

    await click(markAllBtn)
    await waitFor(() => expect(markAllPayload).toEqual({ folder_role: 'inbox' }))
  })

  it('refetches authoritative read state after a partially committed mark-all failure', async () => {
    let serverCommittedOne = false
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-1', email: 'box@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) {
        return json({ items: [row('a', { is_read: serverCommittedOne }), row('b', { is_read: true })], next_cursor: null })
      }
      if (u.includes('/folder-stats')) {
        return json({ folders: [{ folder_id: 'f1', role: 'inbox', total_count: 2, unread_count: serverCommittedOne ? 0 : 1 }] })
      }
      if (u === '/api/auth/me') return json({ csrf_token: 'fake-token' })
      if (u === '/api/mail/mark-all-read') {
        serverCommittedOne = true
        return json({ detail: 'batch failed after one commit' }, 500)
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    const { container } = await render(<MessageList />)
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('2 封邮件 · 1 封未读'))
    await click(container.querySelector('.mark-all-btn'))
    await waitFor(() => expect(container.querySelector('.list-note.error')?.textContent).toContain('标记全部已读失败'))
    await waitFor(() => expect(container.querySelector('.list-count')?.textContent).toBe('2 封邮件 · 0 封未读'))
    expect(container.querySelector('.message-row.unread')).toBeNull()
  })

  it('clicking refresh in unified view triggers syncAll and invalidates cache', async () => {
    let deltaSyncCalled = false
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const u = String(url)
      if (u.includes('/api/mail/sync/delta')) {
        deltaSyncCalled = true
        return json({ id: 'req-1', mode: 'delta', trigger: 'manual', state: 'complete', target_count: 1, queued_count: 0, running_count: 0, completed_count: 1, failed_count: 0, created_at: '2026-10-26T00:00:00Z', errors: [] }, 200)
      }
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-1', email: 'u@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) {
        return json({ items: [], next_cursor: null })
      }
      if (u === '/api/auth/me') return json({ csrf_token: 'fake-token' })
      return json({ detail: 'unexpected' }, 404)
    }))

    useMailStore.setState({ view: { type: 'allInbox' } })
    const { container } = await render(<MessageList />)

    const refreshBtn = container.querySelector('button[aria-label="增量同步（检查新邮件）"]') as HTMLButtonElement
    expect(refreshBtn).not.toBeNull()
    await click(refreshBtn)

    await waitFor(() => expect(deltaSyncCalled).toBe(true))
  })

  it('clicking refresh in single account view triggers scoped delta sync (p046)', async () => {
    let syncedScope: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.includes('/api/mail/sync/delta') && init?.method === 'POST') {
        syncedScope = JSON.parse(String(init.body))
        return json({ id: 'req-2', mode: 'delta', trigger: 'manual', state: 'complete', target_count: 1, queued_count: 0, running_count: 0, completed_count: 1, failed_count: 0, created_at: '2026-10-26T00:00:00Z', errors: [] }, 200)
      }
      if (u.startsWith('/api/accounts')) {
        return json({ accounts: [{ id: 'acc-99', email: 'u@x.test', status: 'active', account_type: 'imap', provider: 'imap' }], total: 1, limit: 200, offset: 0, has_more: false })
      }
      if (u.startsWith('/api/mail/inbox')) {
        return json({ items: [], next_cursor: null })
      }
      if (u.includes('/folder-stats')) {
        return json({ folders: [] })
      }
      if (u === '/api/auth/me') return json({ csrf_token: 'fake-token' })
      return json({ detail: 'unexpected' }, 404)
    }))

    useMailStore.setState({ view: { type: 'account', accountId: 'acc-99', email: 'u@x.test' } })
    const { container } = await render(<MessageList />)

    const refreshBtn = container.querySelector('button[aria-label="增量同步（检查新邮件）"]') as HTMLButtonElement
    expect(refreshBtn).not.toBeNull()
    await click(refreshBtn)

    await waitFor(() => expect(syncedScope).toMatchObject({ account_id: 'acc-99' }))
  })
})


it('keeps unknown read state neutral and does not automatically mark it read', async () => {
  const fallback = globalThis.fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).startsWith('/api/mail/inbox')) return json({ items: [row('unknown', { is_read: null, is_flagged: null, has_attachments: null })], next_cursor: null })
    return fallback(url, init)
  }))
  const { container } = await render(<MessageList />)
  await waitFor(() => expect(subjects(container)).toEqual(['Subject unknown']))
  expect(container.querySelector('.message-row.unread')).toBeNull()
  expect(container.querySelector('[aria-label="未读"]')).toBeNull()
  await click(container.querySelector('.message-row'))
  expect(calls.some((url) => url.includes('/read'))).toBe(false)
})

it('shows unknown search unread count when any loaded result has unknown read status', async () => {
  const fallback = globalThis.fetch
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).startsWith('/api/mail/search')) return json({
      query: 'unknown-status', items: [row('unread'), row('unknown', { is_read: null })],
      total: 2, offset: 0, next_offset: null,
    })
    return fallback(url, init)
  }))
  useMailStore.setState({ search: 'unknown-status' })
  const { container } = await render(<MessageList />)
  await waitFor(() => expect(subjects(container)).toEqual(['Subject unread', 'Subject unknown']))
  expect(container.querySelector('.list-count')?.textContent).toBe('2 封邮件 · — 封未读')
})
