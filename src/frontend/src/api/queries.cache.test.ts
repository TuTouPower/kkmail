import { describe, expect, it, vi } from 'vitest'
import { MAIL_STALE_TIME_MS, applyCachedReadStateWithRollback, fetchAccounts, findCachedMail, queryClient, queryKeys, resetGroupMailQueries, setCachedReadState, type MailItem } from './queries'

describe('mail list cache policy', () => {
  it('keeps lists fresh for several minutes', () => {
    expect(MAIL_STALE_TIME_MS).toBeGreaterThanOrEqual(5 * 60_000)
    expect(queryClient.getDefaultOptions().queries?.staleTime).toBe(MAIL_STALE_TIME_MS)
  })

  it('does not set global placeholderData (detail must not keep previous body)', () => {
    expect(queryClient.getDefaultOptions().queries?.placeholderData).toBeUndefined()
  })

  it('clears every cached group page after a membership change', async () => {
    const inboxKey = queryKeys.inbox('__all__', 'all', 'inbox', 'desc', undefined, 'reset-group')
    const otherInboxKey = queryKeys.inbox('__all__', 'all', 'inbox', 'desc', undefined, 'other-group')
    const searchKey = queryKeys.search('needle', '__all__', 'reset-group')
    const accountKey = queryKeys.inbox('account-1')
    queryClient.setQueryData(inboxKey, { pages: [{ items: ['page-1'] }, { items: ['page-2'] }], pageParams: [null, 'cursor'] })
    queryClient.setQueryData(otherInboxKey, { pages: [{ items: ['old-member'] }], pageParams: [null] })
    queryClient.setQueryData(searchKey, { pages: [{ items: ['page-1'] }, { items: ['page-2'] }], pageParams: [0, 20] })
    queryClient.setQueryData(accountKey, ['unaffected-account-mail'])

    await resetGroupMailQueries()

    expect(queryClient.getQueryData(inboxKey)).toBeUndefined()
    expect(queryClient.getQueryData(otherInboxKey)).toBeUndefined()
    expect(queryClient.getQueryData(searchKey)).toBeUndefined()
    expect(queryClient.getQueryData(accountKey)).toEqual(['unaffected-account-mail'])
  })

  it('loads all account pages beyond the former 20,000-account cap', async () => {
    const total = 20_001
    const offsets: number[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = new URL(String(input), 'http://localhost')
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      offsets.push(offset)
      const end = Math.min(offset + limit, total)
      const accounts = Array.from({ length: end - offset }, (_, index) => ({ id: `account-${offset + index}` }))
      return new Response(JSON.stringify({ accounts, total, limit, offset, has_more: end < total }), {
        headers: { 'Content-Type': 'application/json' },
      })
    }))

    try {
      const accounts = await fetchAccounts()
      expect(accounts).toHaveLength(total)
      expect(offsets).toHaveLength(101)
      expect(offsets.at(-1)).toBe(20_000)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('stops after collecting the reported account total', async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = new URL(String(input), 'http://localhost')
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      const accounts = Array.from({ length: limit }, (_, index) => ({ id: `account-${offset + index}` }))
      return new Response(JSON.stringify({ accounts, total: 200, limit, offset, has_more: true }), {
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    try {
      const accounts = await fetchAccounts()
      expect(accounts).toHaveLength(200)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('rejects account pages that do not match the requested offset', async () => {
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const url = new URL(String(input), 'http://localhost')
      const requestedOffset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      calls += 1
      const offset = calls === 1 ? requestedOffset : 0
      const accounts = Array.from({ length: limit }, (_, index) => ({ id: `account-${offset + index}` }))
      return new Response(JSON.stringify({ accounts, total: 1_000, limit, offset, has_more: true }), {
        headers: { 'Content-Type': 'application/json' },
      })
    }))

    try {
      await expect(fetchAccounts()).rejects.toThrow('unexpected offset')
      expect(calls).toBe(2)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('caps pathological account pagination at 10,000 pages', async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const url = new URL(String(input), 'http://localhost')
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      return new Response(JSON.stringify({
        accounts: [{ id: `account-${offset}` }],
        total: 10_001,
        limit,
        offset,
        has_more: true,
      }), { headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    try {
      await expect(fetchAccounts()).rejects.toThrow('exceeded 10000 pages')
      expect(fetchMock).toHaveBeenCalledTimes(10_000)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

describe('applyCachedReadStateWithRollback (A149)', () => {
  const bulkItem = (id: string): MailItem => ({
    id, subject: `Bulk ${id}`, from: 'a@x.test', accountEmail: 'a@x.test',
    is_read: false, is_flagged: false, has_attachments: false,
  })

  it('reverts keys that no other writer touched after the optimistic write', () => {
    const key = queryKeys.inbox('bulk-rollback-clean')
    queryClient.setQueryData(key, [bulkItem('bulk-clean-a'), bulkItem('bulk-clean-b')])

    const rollback = applyCachedReadStateWithRollback(['bulk-clean-a', 'bulk-clean-b'], true, false)
    expect(queryClient.getQueryData<MailItem[]>(key)?.map((m) => m.is_read)).toEqual([true, true])

    rollback()
    expect(queryClient.getQueryData<MailItem[]>(key)?.map((m) => m.is_read)).toEqual([false, false])
  })

  it('does not clobber a key whose revision advanced after the optimistic write', () => {
    const key = queryKeys.inbox('bulk-rollback-touched')
    queryClient.setQueryData(key, [bulkItem('bulk-touched-a')])

    const rollback = applyCachedReadStateWithRollback(['bulk-touched-a'], true, false)
    // Another writer re-asserts the read state through the shared cache
    // helper; that advances the per-key revision, so the bulk rollback
    // must leave the key alone even though the value matches its own
    // optimistic write.
    setCachedReadState(['bulk-touched-a'], true)

    rollback()
    expect(queryClient.getQueryData<MailItem[]>(key)?.[0].is_read).toBe(true)
  })

  it('does not clobber a key whose cached copies diverged after the optimistic write', () => {
    const inboxKey = queryKeys.inbox('bulk-rollback-diverged')
    const searchKey = queryKeys.search('bulk-needle', 'bulk-rollback-diverged')
    const original = bulkItem('bulk-diverged-a')
    queryClient.setQueryData(inboxKey, [original])
    queryClient.setQueryData(searchKey, [original])

    const rollback = applyCachedReadStateWithRollback(['bulk-diverged-a'], true, false)
    // A newer list copy now disagrees with the optimistic value.
    queryClient.setQueryData(searchKey, [{ ...original, is_read: false }])

    rollback()
    expect(queryClient.getQueryData<MailItem[]>(inboxKey)?.[0].is_read).toBe(true)
    expect(queryClient.getQueryData<MailItem[]>(searchKey)?.[0].is_read).toBe(false)
  })
})

describe('findCachedMail', () => {
  it('prioritizes latest cache entries or current view over older cached lists', () => {
    const olderItem: MailItem = { id: 'm-1', subject: 'Old', from: 'a@x.test', accountEmail: 'a@x.test', is_read: false, is_flagged: false, has_attachments: false }
    const newerItem: MailItem = { id: 'm-1', subject: 'New', from: 'a@x.test', accountEmail: 'a@x.test', is_read: true, is_flagged: true, has_attachments: false }

    const oldQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('old-scope') })
    oldQuery.setData([olderItem], { updatedAt: 1000, manual: true })

    const newQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('new-scope') })
    newQuery.setData([newerItem], { updatedAt: 2000, manual: true })

    const hit = findCachedMail('m-1')
    expect(hit?.subject).toBe('New')
    expect(hit?.is_read).toBe(true)
  })

  it('prioritizes current view scope over other lists', async () => {
    const { useMailStore } = await import('../store/mailStore')
    useMailStore.setState({ view: { type: 'account', accountId: 'current-acc', email: 'c@x.test' } })
    const itemInOther: MailItem = { id: 'm-2', subject: 'Other Scope', from: 'a@x.test', accountEmail: 'a@x.test', is_read: false, is_flagged: false, has_attachments: false }
    const itemInCurrent: MailItem = { id: 'm-2', subject: 'Current Scope', from: 'a@x.test', accountEmail: 'a@x.test', is_read: true, is_flagged: false, has_attachments: false }

    const otherQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('other-scope') })
    otherQuery.setData([itemInOther], { updatedAt: 9000, manual: true })

    const currentQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('current-acc') })
    currentQuery.setData([itemInCurrent], { updatedAt: 1000, manual: true })

    const hit = findCachedMail('m-2')
    expect(hit?.subject).toBe('Current Scope')
  })

  it('prioritizes folder, favorite with accountId, and group scopes (AC-003)', async () => {
    const { useMailStore } = await import('../store/mailStore')
    const itemInAccount: MailItem = { id: 'm-scope', subject: 'Account Scope', from: 'a@x.test', accountEmail: 'a@x.test', is_read: true, is_flagged: false, has_attachments: false }
    const itemInGroup: MailItem = { id: 'm-scope', subject: 'Group Scope', from: 'a@x.test', accountEmail: 'a@x.test', is_read: false, is_flagged: true, has_attachments: false }
    const itemInAll: MailItem = { id: 'm-scope', subject: 'All Scope', from: 'a@x.test', accountEmail: 'a@x.test', is_read: false, is_flagged: false, has_attachments: false }

    const accQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('acc-scope') })
    accQuery.setData([itemInAccount], { updatedAt: 1000, manual: true })

    const grpQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('__all__', undefined, 'inbox', 'desc', undefined, 'grp-1') })
    grpQuery.setData([itemInGroup], { updatedAt: 1000, manual: true })

    const allQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('__all__') })
    allQuery.setData([itemInAll], { updatedAt: 9000, manual: true })

    // folder view
    useMailStore.setState({ view: { type: 'folder', accountId: 'acc-scope', email: 'a@x.test', folderId: 'f-1', folderName: 'F', folderRole: 'inbox' } })
    expect(findCachedMail('m-scope')?.subject).toBe('Account Scope')

    // favorite view with accountId
    useMailStore.setState({ view: { type: 'favorite', category: 'unread', accountId: 'acc-scope', email: 'a@x.test' } })
    expect(findCachedMail('m-scope')?.subject).toBe('Account Scope')

    // group view
    useMailStore.setState({ view: { type: 'group', groupId: 'grp-1', groupName: 'G', category: 'inbox' } })
    expect(findCachedMail('m-scope')?.subject).toBe('Group Scope')
  })

  it('finds and optimistically patches a bare PageOut cache entry', () => {
    const item: MailItem = {
      id: 'plain-page-mail', subject: 'PageOut', from: 'a@x.test', accountEmail: 'a@x.test',
      is_read: false, is_flagged: false, has_attachments: false,
    }
    const page = { items: [item], total: 1, offset: 0, next_offset: null }
    const key = queryKeys.inbox('plain-page')
    queryClient.setQueryData(key, page)

    expect(findCachedMail(item.id)).toEqual(item)
    setCachedReadState([item.id], true)
    expect(queryClient.getQueryData(key)).toEqual({ ...page, items: [{ ...item, is_read: true }] })
  })

})

describe('cache isolation from non-list query keys (AC-001)', () => {
  it('does not throw mailKey error or corrupt account-folders when executing cache helpers', async () => {
    const { markReadOptimistic, flagOptimistic, setCachedReadState, removeCachedMail } = await import('./queries')
    const sampleItem: MailItem = { id: 'msg-isolated', subject: 'Test', from: 'a@x.test', accountEmail: 'a@x.test', is_read: false, is_flagged: false, has_attachments: false }
    const folderStats = [{ folder_id: 'folder-junk', name: '垃圾邮件', role: 'junk', unread_count: 2, total_count: 2 }]

    // Seed non-list queries under mail-core prefix
    queryClient.setQueryData(['mail-core', 'account-folders', 'acc-1'], folderStats)
    queryClient.setQueryData(['mail-core', 'stats'], { total_unread: 2, accounts: [] })
    queryClient.setQueryData(['mail-core', 'folder-stats', 'acc-1', 'junk', 'folder-junk'], { total: 2, unread: 2 })

    // Seed real mail list query
    queryClient.setQueryData(queryKeys.inbox('acc-1'), [sampleItem])

    vi.stubGlobal('fetch', vi.fn(async (input: string | URL) => {
      const u = String(input)
      if (u.includes('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'test-tok' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))

    // None of these should throw "mailKey requires a non-empty message id"
    expect(findCachedMail('msg-isolated')?.id).toBe('msg-isolated')
    await markReadOptimistic([sampleItem])
    await flagOptimistic(sampleItem, true)
    setCachedReadState(['msg-isolated'], false)
    removeCachedMail(['msg-isolated'])

    // The account-folders cache should be completely intact
    expect(queryClient.getQueryData(['mail-core', 'account-folders', 'acc-1'])).toEqual(folderStats)
  })
})

it('restores null read and flag states after failed explicit mutations', async () => {
  const { flagOptimistic, setReadOptimistic } = await import('./queries')
  const item: MailItem = { id: 'unknown-state', subject: 'Unknown', from: 'a@x.test', accountEmail: 'a@x.test', is_read: null, is_flagged: null, has_attachments: null }
  const key = queryKeys.inbox('__all__')
  queryClient.setQueryData(key, [item])
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'failed' }), { status: 500, headers: { 'Content-Type': 'application/json' } })))
  await expect(setReadOptimistic([item], true)).rejects.toThrow()
  expect(queryClient.getQueryData<MailItem[]>(key)?.[0].is_read).toBeNull()
  await expect(flagOptimistic(item, true)).rejects.toThrow()
  expect(queryClient.getQueryData<MailItem[]>(key)?.[0].is_flagged).toBeNull()
})

it('restores the cached null read state when a stale false item mutation fails', async () => {
  const { setReadOptimistic } = await import('./queries')
  const item: MailItem = { id: 'stale-state', subject: 'Unknown', from: 'a@x.test', accountEmail: 'a@x.test', is_read: null, is_flagged: null, has_attachments: null }
  const key = queryKeys.inbox('__all__')
  queryClient.setQueryData(key, [item])
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500, headers: { 'Content-Type': 'application/json' } })))
  await expect(setReadOptimistic([{ ...item, is_read: false }], true)).rejects.toThrow()
  expect(queryClient.getQueryData<MailItem[]>(key)?.[0].is_read).toBeNull()
})
