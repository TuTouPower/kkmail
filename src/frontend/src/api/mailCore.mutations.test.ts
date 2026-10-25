import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests } from './client'
import { mailKey } from '../lib/mailKey'
import { fetchMailCoreInbox, fetchMailCoreSearch, postMailCoreMarkAllRead, postMailCoreMessageFlag, postMailCoreMessageRead } from './mailCore'
import { ALL_ACCOUNTS, beginReadMutation, flagOptimistic, invalidateMailStatsQueries, markReadOptimistic, queryClient, queryKeys, setCachedReadState, setReadOptimistic, type MailItem } from './queries'

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
  locations: [],
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
  it('updates only matching account, group, role, and folder unread caches', async () => {
    const message = item({ locations: [
      { folder_id: 'inbox-1', role: 'inbox' },
      { folder_id: 'inbox-2', role: 'inbox' },
      { folder_id: 'archive-1', role: 'archive' },
    ] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [message])
    queryClient.setQueryData(queryKeys.accounts, [
      { id: 'acc-1', sync_enabled: true, group_id: 'group-1' },
      { id: 'acc-2', sync_enabled: true, group_id: 'group-2' },
    ])
    queryClient.setQueryData(queryKeys.stats, {
      totalUnread: 4,
      byAccount: new Map([['acc-1', 3], ['acc-2', 1]]),
    })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'all', 'inbox', ''], { total: 20, unread: 4 })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'group:group-1', 'inbox', ''], { total: 12, unread: 3 })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'group:group-2', 'inbox', ''], { total: 8, unread: 1 })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'account:acc-1', 'inbox', 'inbox-1'], { total: 4, unread: 2 })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'account:acc-1', 'archive', 'archive-1'], { total: 5, unread: 1 })
    queryClient.setQueryData(['mail-core', 'account-folders', 'acc-1'], [
      { folder_id: 'inbox-1', role: 'inbox', total_count: 4, unread_count: 2 },
      { folder_id: 'inbox-2', role: 'inbox', total_count: 2, unread_count: 1 },
      { folder_id: 'archive-1', role: 'archive', total_count: 5, unread_count: 1 },
    ])
    stubFetch(() => json(200, { id: message.id, is_read: true }))

    await setReadOptimistic([message], true)

    const stats = queryClient.getQueryData<{ totalUnread: number; byAccount: Map<string, number> }>(queryKeys.stats)!
    expect(stats.totalUnread).toBe(2)
    expect(stats.byAccount.get('acc-1')).toBe(1)
    expect(stats.byAccount.get('acc-2')).toBe(1)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0]).toMatchObject({ is_read: true })
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'all', 'inbox', ''])).toEqual({ total: 20, unread: 2 })
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'group:group-1', 'inbox', ''])).toEqual({ total: 12, unread: 1 })
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'group:group-2', 'inbox', ''])).toEqual({ total: 8, unread: 1 })
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'account:acc-1', 'inbox', 'inbox-1'])).toEqual({ total: 4, unread: 1 })
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'account:acc-1', 'archive', 'archive-1'])).toEqual({ total: 5, unread: 0 })
    expect(queryClient.getQueryData<Array<{ folder_id: string; unread_count: number }>>(['mail-core', 'account-folders', 'acc-1'])?.map((folder) => folder.unread_count)).toEqual([1, 0, 0])
  })

  it('keeps unknown read statistics unknown and actively invalidates stats after the request', async () => {
    const unknownRead = item({ is_read: null, locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [unknownRead])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: null, byAccount: new Map([['acc-1', null]]) })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'all', 'inbox', ''], { total: 4, unread: null })
    stubFetch(() => json(200, { id: unknownRead.id, is_read: true }))

    await setReadOptimistic([unknownRead], true)

    expect(queryClient.getQueryData<{ totalUnread: number | null }>(queryKeys.stats)?.totalUnread).toBeNull()
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'all', 'inbox', ''])).toEqual({ total: 4, unread: null })
    expect(queryClient.getQueryState(queryKeys.stats)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(['mail-core', 'folder-stats', 'all', 'inbox', ''])?.isInvalidated).toBe(true)
  })

  it('cancels in-flight list and stats reads before applying optimistic state', async () => {
    const message = item({ locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    const inboxKey = queryKeys.inbox(ALL_ACCOUNTS)
    queryClient.setQueryData(inboxKey, [message])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 1, byAccount: new Map([['acc-1', 1]]) })
    let startedCount = 0
    let started!: () => void
    const bothStarted = new Promise<void>((resolve) => { started = resolve })
    let releaseList!: (items: MailItem[]) => void
    let releaseStats!: (stats: { totalUnread: number; byAccount: Map<string, number> }) => void
    const staleList = new Promise<MailItem[]>((resolve) => { releaseList = resolve })
    const staleStats = new Promise<{ totalUnread: number; byAccount: Map<string, number> }>((resolve) => { releaseStats = resolve })
    const listRefresh = queryClient.fetchQuery({
      queryKey: inboxKey,
      staleTime: 0,
      queryFn: () => { if (++startedCount === 2) started(); return staleList },
    }).catch(() => undefined)
    const statsRefresh = queryClient.fetchQuery({
      queryKey: queryKeys.stats,
      staleTime: 0,
      queryFn: () => { if (++startedCount === 2) started(); return staleStats },
    }).catch(() => undefined)
    await bothStarted
    stubFetch(() => json(200, { id: message.id, is_read: true }))

    await setReadOptimistic([message], true)

    expect(queryClient.getQueryData<MailItem[]>(inboxKey)?.[0].is_read).toBe(true)
    expect(queryClient.getQueryData<{ totalUnread: number }>(queryKeys.stats)?.totalUnread).toBe(0)
    releaseList([item({ is_read: false, locations: message.locations })])
    releaseStats({ totalUnread: 1, byAccount: new Map([['acc-1', 1]]) })
    await Promise.all([listRefresh, statsRefresh])
    expect(queryClient.getQueryData<MailItem[]>(inboxKey)?.[0].is_read).toBe(true)
    expect(queryClient.getQueryData<{ totalUnread: number }>(queryKeys.stats)?.totalUnread).toBe(0)
  })

  it('serializes concurrent opposite read requests and preserves the latest intent on an older failure', async () => {
    const original = item({ locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [original])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 1, byAccount: new Map([['acc-1', 1]]) })
    let releaseFirst!: () => void
    let startedFirst!: () => void
    const firstStarted = new Promise<void>((resolve) => { startedFirst = resolve })
    const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve })
    let requests = 0
    stubFetch(async () => {
      requests += 1
      if (requests === 1) {
        startedFirst()
        await firstGate
        return json(500, { detail: 'first write failed' })
      }
      return json(200, { id: original.id, is_read: false })
    })

    const first = setReadOptimistic([original], true)
    await firstStarted
    const second = setReadOptimistic([item({ is_read: true, locations: original.locations })], false)
    releaseFirst()
    await expect(first).rejects.toThrow('first write failed')
    await second

    expect(requests).toBe(2)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(false)
    expect(queryClient.getQueryData<{ totalUnread: number }>(queryKeys.stats)?.totalUnread).toBe(1)
  })

  it('serializes mark-all against single-message read requests in both directions', async () => {
    const firstItem = item({ id: 'single-1', locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    const secondItem = item({ id: 'single-2', locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [firstItem, secondItem])
    let releaseFirst!: () => void
    let startFirst!: () => void
    let startSecond!: () => void
    const firstStarted = new Promise<void>((resolve) => { startFirst = resolve })
    const secondStarted = new Promise<void>((resolve) => { startSecond = resolve })
    const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve })
    let secondRequestStarted = false
    stubFetch(async (url) => {
      if (url.endsWith('/messages/single-1/read')) {
        startFirst()
        await firstGate
      }
      if (url.endsWith('/messages/single-2/read')) {
        secondRequestStarted = true
        startSecond()
      }
      return json(200, { is_read: true })
    })

    const firstRead = setReadOptimistic([firstItem], true)
    await firstStarted
    let bulkAcquired = false
    const bulkFinishPromise = beginReadMutation().then((finish) => {
      bulkAcquired = true
      return finish
    })
    await Promise.resolve()
    expect(bulkAcquired).toBe(false)
    releaseFirst()
    await firstRead
    const finishBulk = await bulkFinishPromise

    const secondRead = setReadOptimistic([secondItem], true)
    await Promise.resolve()
    expect(secondRequestStarted).toBe(false)
    await finishBulk()
    await secondStarted
    await secondRead
    expect(secondRequestStarted).toBe(true)
  })

  it('holds the mark-all gate until its final stats refresh settles', async () => {
    const message = item({ locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [message])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 1, byAccount: new Map([['acc-1', 1]]) })
    const finishBulk = await beginReadMutation()
    setCachedReadState([mailKey(message)], true)
    await invalidateMailStatsQueries()

    let releaseRefresh!: () => void
    let refreshStarted!: () => void
    const started = new Promise<void>((resolve) => { refreshStarted = resolve })
    const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve })
    vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(async () => {
      refreshStarted()
      await refreshGate
    })
    const finishPromise = finishBulk()
    await started
    const cancelSpy = vi.spyOn(queryClient, 'cancelQueries')
    const queuedNoop = setReadOptimistic([item({ is_read: true, locations: message.locations })], true)
    await Promise.resolve()
    expect(cancelSpy).not.toHaveBeenCalled()

    releaseRefresh()
    await finishPromise
    await queuedNoop
    expect(cancelSpy).toHaveBeenCalledTimes(1)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(true)
  })

  it('does not cancel a final stats refresh for a duplicate same-state single read', async () => {
    const message = item({ locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [message])
    let releaseWrite!: () => void
    let writeStarted!: () => void
    const writeGate = new Promise<void>((resolve) => { releaseWrite = resolve })
    const startedWrite = new Promise<void>((resolve) => { writeStarted = resolve })
    stubFetch(async () => {
      writeStarted()
      await writeGate
      return json(200, { id: message.id, is_read: true })
    })

    const firstRead = setReadOptimistic([message], true)
    await startedWrite
    const cancelSpy = vi.spyOn(queryClient, 'cancelQueries')
    let releaseRefresh!: () => void
    let refreshStarted!: () => void
    const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve })
    const startedRefresh = new Promise<void>((resolve) => { refreshStarted = resolve })
    vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(async () => {
      refreshStarted()
      await refreshGate
    })
    releaseWrite()
    await startedRefresh

    const cancelCount = cancelSpy.mock.calls.length
    await setReadOptimistic([item({ ...message, is_read: true })], true)
    expect(cancelSpy).toHaveBeenCalledTimes(cancelCount)

    releaseRefresh()
    await firstRead
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(true)
  })

  it('does not cancel an external stats refresh for a same-state no-op', async () => {
    const message = item({ is_read: true })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [message])
    let releaseStats!: (stats: { totalUnread: number; byAccount: Map<string, number> }) => void
    let statsStarted!: () => void
    const statsGate = new Promise<{ totalUnread: number; byAccount: Map<string, number> }>((resolve) => { releaseStats = resolve })
    const startedStats = new Promise<void>((resolve) => { statsStarted = resolve })
    const statsRefresh = queryClient.fetchQuery({
      queryKey: queryKeys.stats,
      staleTime: 0,
      queryFn: () => { statsStarted(); return statsGate },
    })
    await startedStats
    const cancelSpy = vi.spyOn(queryClient, 'cancelQueries')

    await setReadOptimistic([message], true)

    expect(cancelSpy).not.toHaveBeenCalled()
    expect(queryClient.getQueryState(queryKeys.stats)?.fetchStatus).toBe('fetching')
    releaseStats({ totalUnread: 0, byAccount: new Map([['acc-1', 0]]) })
    await statsRefresh
  })

  it('requeues list and stats refreshes when a new read joins the final refresh', async () => {
    const message = item({ locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [message])
    let releaseRefresh!: () => void
    let refreshStarted!: () => void
    let secondWriteStarted!: () => void
    const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve })
    const startedRefresh = new Promise<void>((resolve) => { refreshStarted = resolve })
    const startedSecondWrite = new Promise<void>((resolve) => { secondWriteStarted = resolve })
    let invalidationCount = 0
    vi.spyOn(queryClient, 'invalidateQueries').mockImplementation(async () => {
      invalidationCount += 1
      if (invalidationCount === 1) {
        refreshStarted()
        await refreshGate
      }
    })
    stubFetch((_url, init) => {
      const nextRead = JSON.parse(String(init.body)).is_read as boolean
      if (!nextRead) secondWriteStarted()
      return json(200, { id: message.id, is_read: nextRead })
    })

    const firstRead = setReadOptimistic([message], true)
    await startedRefresh
    const secondRead = setReadOptimistic([item({ ...message, is_read: true })], false)
    await startedSecondWrite
    releaseRefresh()
    await Promise.all([firstRead, secondRead])

    expect(invalidationCount).toBe(3)
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(false)
  })

  it('markReadOptimistic reverts on failure', async () => {
    const message = item({ locations: [{ folder_id: 'inbox-1', role: 'inbox' }] })
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), [message])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 1, byAccount: new Map([['acc-1', 1]]) })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'all', 'inbox', ''], { total: 1, unread: 1 })
    stubFetch(() => json(500, { detail: 'boom' }))
    await expect(markReadOptimistic([message])).rejects.toThrow('boom')
    expect(queryClient.getQueryData<MailItem[]>(queryKeys.inbox(ALL_ACCOUNTS))?.[0].is_read).toBe(false)
    expect(queryClient.getQueryData<{ totalUnread: number }>(queryKeys.stats)?.totalUnread).toBe(1)
    expect(queryClient.getQueryData(['mail-core', 'folder-stats', 'all', 'inbox', ''])).toEqual({ total: 1, unread: 1 })
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

  it('keeps query-cache scans constant for a batch read mutation', async () => {
    const items = Array.from({ length: 20 }, (_, index) => item({ id: `bulk-${index}` }))
    queryClient.setQueryData(queryKeys.inbox(ALL_ACCOUNTS), items)
    stubFetch(() => json(200, { is_read: true }))
    const findAll = vi.spyOn(queryClient.getQueryCache(), 'findAll')

    await setReadOptimistic(items, true)

    expect(findAll).toHaveBeenCalledTimes(5)
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
