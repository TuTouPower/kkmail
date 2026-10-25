import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests } from './client'
import { fetchMailCoreInbox, fetchMailCoreSearch, postMailCoreMarkAllRead, postMailCoreMessageFlag, postMailCoreMessageRead } from './mailCore'
import { ALL_ACCOUNTS, flagOptimistic, markReadOptimistic, queryClient, queryKeys, setCachedReadState, setReadOptimistic, type MailItem } from './queries'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Route /api/auth/me to a CSRF token; everything else to `handler`. */
function stubFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const mock = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (String(url).endsWith('/api/auth/me')) return json(200, { csrf_token: 'tok' })
    return handler(String(url), init)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

const item = (over: Partial<MailItem> = {}): MailItem => ({
  id: 'uuid-1',
  subject: 'S',
  from: 'a@b.c',
  is_read: false,
  is_flagged: false,
  has_attachments: false,
  accountEmail: 'acc@x.test',
  accountId: 'acc-1',
  folder: 'inbox',
  ...over,
})

afterEach(() => {
  vi.unstubAllGlobals()
  queryClient.clear()
  __resetCsrfForTests()
})

describe('mail-core mutations', () => {
  it('POSTs an explicit read body with the CSRF header', async () => {
    const mock = stubFetch(() => json(200, { id: 'm1', is_read: false }))
    const out = await postMailCoreMessageRead('m1', false)
    expect(out.is_read).toBe(false)
    const [url, init] = mock.mock.calls.at(-1) as unknown as [string, RequestInit]
    expect(url).toBe('/api/mail/messages/m1/read')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('tok')
    expect(JSON.parse(String(init.body))).toEqual({ is_read: false })
  })

  it('POSTs an explicit flag body', async () => {
    const mock = stubFetch(() => json(200, { id: 'm1', is_flagged: true }))
    await postMailCoreMessageFlag('m1', true)
    const [url, init] = mock.mock.calls.at(-1) as unknown as [string, RequestInit]
    expect(url).toBe('/api/mail/messages/m1/flag')
    expect(JSON.parse(String(init.body))).toEqual({ is_flagged: true })
  })
})

describe('list queries', () => {
  it('passes the opaque cursor and account filter', async () => {
    const mock = stubFetch(() => json(200, { items: [], next_cursor: null }))
    await fetchMailCoreInbox({ accountId: 'acc-1', cursor: 'abc', limit: 10 })
    expect(String(mock.mock.calls[0][0])).toBe('/api/mail/inbox?limit=10&account_id=acc-1&cursor=abc')
  })

  it('passes group scope to inbox, search, and mark-all-read requests', async () => {
    const mock = stubFetch((url) => {
      if (url.includes('/mark-all-read')) return json(200, { success: true, count: 1 })
      if (url.includes('/search')) return json(200, { query: 'tax', items: [], total: 0, offset: 0, next_offset: null })
      return json(200, { items: [], next_cursor: null })
    })
    await fetchMailCoreInbox({ groupId: 'group-1' })
    await fetchMailCoreSearch('tax', { groupId: 'group-1' })
    await postMailCoreMarkAllRead({ groupId: 'group-1', folder_role: 'inbox' })
    const requests = mock.mock.calls as unknown as Array<[string, RequestInit]>
    expect(requests.some(([url]) => url.includes('/api/mail/inbox?') && url.includes('group_id=group-1'))).toBe(true)
    expect(requests.some(([url]) => url.includes('/api/mail/search?') && url.includes('group_id=group-1'))).toBe(true)
    const markAll = requests.find(([url]) => url.endsWith('/api/mail/mark-all-read'))
    expect(JSON.parse(String(markAll?.[1].body))).toEqual({ folder_role: 'inbox', group_id: 'group-1' })
  })

  it('search uses offset pagination', async () => {
    const mock = stubFetch(() => json(200, { query: 'hi', items: [], total: 0, offset: 50, next_offset: null }))
    const page = await fetchMailCoreSearch('hi', { offset: 50 })
    expect(page.total).toBe(0)
    expect(String(mock.mock.calls[0][0])).toBe('/api/mail/search?q=hi&limit=50&offset=50')
  })

  it('search includes the selected folder scope', async () => {
    const mock = stubFetch(() => json(200, { query: 'invoice', items: [], total: 0, offset: 0, next_offset: null }))
    await fetchMailCoreSearch('invoice', { accountId: 'acc-1', folderId: 'folder-1' })
    expect(String(mock.mock.calls[0][0])).toBe('/api/mail/search?q=invoice&limit=50&offset=0&account_id=acc-1&folder_id=folder-1')
  })
})

describe('optimistic updates', () => {
  it('markReadOptimistic reverts on failure', async () => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item()])
    stubFetch(() => json(500, { detail: 'boom' }))
    await expect(markReadOptimistic([item()])).rejects.toThrow('boom')
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(false)
  })

  it('markReadOptimistic reverts when HTTP 200 reports success=false', async () => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item()])
    stubFetch(() => json(200, { success: false }))

    await expect(markReadOptimistic([item()])).rejects.toThrow('服务器未接受已读状态更新')
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(false)
  })

  it('preserves interleaved read state on failure and invalidates mail lists', async () => {
    const inboxKey = queryKeys.inbox(ALL_ACCOUNTS)
    const searchKey = queryKeys.search('needle', ALL_ACCOUNTS)
    const unknownRead = item({ is_read: null })
    queryClient.setQueryData(inboxKey, [unknownRead])
    queryClient.setQueryData(searchKey, [unknownRead])
    stubFetch(() => {
      setCachedReadState([unknownRead.id], false)
      return json(500, { detail: 'boom' })
    })

    await expect(setReadOptimistic([unknownRead], true)).rejects.toThrow('boom')

    expect(queryClient.getQueryData<MailItem[]>(inboxKey)?.[0].is_read).toBe(false)
    expect(queryClient.getQueryData<MailItem[]>(searchKey)?.[0].is_read).toBe(false)
    expect(queryClient.getQueryState(inboxKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(searchKey)?.isInvalidated).toBe(true)
  })

  it('markReadOptimistic keeps the read state on success', async () => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item()])
    stubFetch(() => json(200, { id: 'uuid-1', is_read: true }))
    await markReadOptimistic([item()])
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(true)
  })

  it('indexes list caches once for a batch read mutation', async () => {
    const items = Array.from({ length: 20 }, (_, index) => item({ id: `bulk-${index}` }))
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), items)
    stubFetch(() => json(200, { is_read: true }))
    const findAll = vi.spyOn(queryClient.getQueryCache(), 'findAll')

    await setReadOptimistic(items, true)

    expect(findAll).toHaveBeenCalledTimes(2)
  })

  it('bounds read mutation concurrency and stops after a failed batch', async () => {
    const items = Array.from({ length: 101 }, (_, index) => item({ id: `uuid-${index}` }))
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), items)
    const mock = stubFetch((url) =>
      url.endsWith('/messages/uuid-0/read') ? json(503, { detail: 'stop' }) : json(200, { is_read: true }),
    )

    await expect(markReadOptimistic(items)).rejects.toThrow('stop')

    const readRequests = mock.mock.calls.filter(([url]) => String(url).includes('/messages/') && String(url).endsWith('/read'))
    expect(readRequests).toHaveLength(50)
    const cached = queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS)) ?? []
    expect(cached.find((message) => message.id === 'uuid-0')?.is_read).toBe(false)
    expect(cached.find((message) => message.id === 'uuid-1')?.is_read).toBe(true)
    expect(cached.find((message) => message.id === 'uuid-50')?.is_read).toBe(false)
  })

  it('never runs more than 50 read mutations concurrently', async () => {
    const items = Array.from({ length: 101 }, (_, index) => item({ id: `uuid-${index}` }))
    let active = 0
    let maxActive = 0
    const mock = stubFetch(async () => {
      active += 1
      maxActive = Math.max(maxActive, active)
      await new Promise((resolve) => setTimeout(resolve, 0))
      active -= 1
      return json(200, { is_read: true })
    })

    await markReadOptimistic(items)

    const readRequests = mock.mock.calls.filter(([url]) => String(url).includes('/messages/') && String(url).endsWith('/read'))
    expect(readRequests).toHaveLength(101)
    expect(maxActive).toBeLessThanOrEqual(50)
  })

  it('flagOptimistic patches every cached list and reverts on failure', async () => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item()])
    queryClient.setQueryData(queryKeys.search('s', ALL_ACCOUNTS), [item()])
    stubFetch(() => json(200, { id: 'uuid-1', is_flagged: true }))
    await flagOptimistic(item(), true)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_flagged).toBe(true)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.search('s', ALL_ACCOUNTS))?.[0].is_flagged).toBe(true)

    stubFetch(() => json(503, { detail: 'down' }))
    await expect(flagOptimistic(item({ is_flagged: true }), false)).rejects.toMatchObject({ status: 503 })
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_flagged).toBe(true)
  })

  it('flagOptimistic reverts when HTTP 200 reports success=false', async () => {
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item()])
    stubFetch(() => json(200, { success: false }))

    await expect(flagOptimistic(item(), true)).rejects.toThrow('服务器未接受旗标更新')
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_flagged).toBe(false)
  })

  it('flagOptimistic restores the prior cache snapshot (not a blind re-toggle)', async () => {
    // Cache already flagged; caller passes a stale item that still says false and asks for true.
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [item({ is_flagged: true })])
    stubFetch(() => json(503, { detail: 'down' }))
    await expect(flagOptimistic(item({ is_flagged: false }), true)).rejects.toMatchObject({ status: 503 })
    // Prior snapshot was true — must not become !nextFlagged (false).
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_flagged).toBe(true)
  })
})
