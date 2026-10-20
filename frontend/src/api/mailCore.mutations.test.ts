import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests } from './client'
import { fetchMailCoreInbox, fetchMailCoreSearch, postMailCoreMessageFlag, postMailCoreMessageRead } from './mailCore'
import { flagOptimistic, markReadOptimistic, queryClient, queryKeys, type MailItem } from './queries'

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
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok')
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

  it('search uses offset pagination', async () => {
    const mock = stubFetch(() => json(200, { query: 'hi', items: [], total: 0, offset: 50, next_offset: null }))
    const page = await fetchMailCoreSearch('hi', { offset: 50 })
    expect(page.total).toBe(0)
    expect(String(mock.mock.calls[0][0])).toBe('/api/mail/search?q=hi&limit=50&offset=50')
  })
})

describe('optimistic updates', () => {
  it('markReadOptimistic reverts on failure', async () => {
    queryClient.setQueryData(queryKeys.inbox('all'), [item()])
    stubFetch(() => json(500, { detail: 'boom' }))
    await expect(markReadOptimistic([item()])).rejects.toThrow('boom')
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox('all'))?.[0].is_read).toBe(false)
  })

  it('markReadOptimistic keeps the read state on success', async () => {
    queryClient.setQueryData(queryKeys.inbox('all'), [item()])
    stubFetch(() => json(200, { id: 'uuid-1', is_read: true }))
    await markReadOptimistic([item()])
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox('all'))?.[0].is_read).toBe(true)
  })

  it('flagOptimistic patches every cached list and reverts on failure', async () => {
    queryClient.setQueryData(queryKeys.inbox('all'), [item()])
    queryClient.setQueryData(queryKeys.search('s', 'all'), [item()])
    stubFetch(() => json(200, { id: 'uuid-1', is_flagged: true }))
    await flagOptimistic(item(), true)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox('all'))?.[0].is_flagged).toBe(true)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.search('s', 'all'))?.[0].is_flagged).toBe(true)

    stubFetch(() => json(503, { detail: 'down' }))
    await expect(flagOptimistic(item({ is_flagged: true }), false)).rejects.toMatchObject({ status: 503 })
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox('all'))?.[0].is_flagged).toBe(true)
  })
})
