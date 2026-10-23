import { describe, expect, it, vi } from 'vitest'
import { MAIL_STALE_TIME_MS, fetchAccounts, findCachedMail, queryClient, queryKeys, resetGroupMailQueries, type MailItem } from './queries'

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
