import { describe, expect, it } from 'vitest'
import { MAIL_STALE_TIME_MS, findCachedMail, queryClient, queryKeys, type MailItem } from './queries'

describe('mail list cache policy', () => {
  it('keeps lists fresh for several minutes', () => {
    expect(MAIL_STALE_TIME_MS).toBeGreaterThanOrEqual(5 * 60_000)
    expect(queryClient.getDefaultOptions().queries?.staleTime).toBe(MAIL_STALE_TIME_MS)
  })

  it('does not set global placeholderData (detail must not keep previous body)', () => {
    expect(queryClient.getDefaultOptions().queries?.placeholderData).toBeUndefined()
  })
})

describe('findCachedMail', () => {
  it('prioritizes latest cache entries or current view over older cached lists', () => {
    const olderItem: MailItem = { id: 'm-1', subject: 'Old', from: 'a@x.test', accountEmail: 'a@x.test', is_read: false, is_flagged: false, has_attachments: false }
    const newerItem: MailItem = { id: 'm-1', subject: 'New', from: 'a@x.test', accountEmail: 'a@x.test', is_read: true, is_flagged: true, has_attachments: false }

    const oldQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('old-scope') })
    oldQuery.setData([olderItem], { updatedAt: 1000 })

    const newQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('new-scope') })
    newQuery.setData([newerItem], { updatedAt: 2000 })

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
    otherQuery.setData([itemInOther], { updatedAt: 9000 })

    const currentQuery = queryClient.getQueryCache().build(queryClient, { queryKey: queryKeys.inbox('current-acc') })
    currentQuery.setData([itemInCurrent], { updatedAt: 1000 })

    const hit = findCachedMail('m-2')
    expect(hit?.subject).toBe('Current Scope')
  })
})
