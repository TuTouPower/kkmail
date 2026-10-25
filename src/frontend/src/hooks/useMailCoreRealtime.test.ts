// @vitest-environment jsdom
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { createThrottledInvalidator, extractMessageIds, shouldInvalidateMailCoreInbox, useMailCoreRealtime } from './useMailCoreRealtime'
import { queryClient, queryKeys, setReadOptimistic, type MailItem } from '../api/queries'
import * as sseModule from '../api/sseStream'
import { UNAUTHORIZED_EVENT } from '../api/client'
import { render, cleanup } from '../test/render'

describe('shouldInvalidateMailCoreInbox', () => {
  it('invalidates on mail / folder stats change events', () => {
    expect(shouldInvalidateMailCoreInbox('message.upserted')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('message.removed')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('folder.stats_updated')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('remote_operation.updated')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('client.resync_hint')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('sync.completed')).toBe(true)
    expect(shouldInvalidateMailCoreInbox('account.updated')).toBe(true)
  })

  it('ignores progress-only events', () => {
    expect(shouldInvalidateMailCoreInbox('sync.progress')).toBe(false)
    expect(shouldInvalidateMailCoreInbox('message')).toBe(false)
  })
})

describe('extractMessageIds', () => {
  it('extracts ids from object payloads', () => {
    expect(extractMessageIds({ message_id: 'm-1' })).toEqual(['m-1'])
    expect(extractMessageIds({ id: 'm-2' })).toEqual(['m-2'])
    expect(extractMessageIds({ message_ids: ['m-3', 'm-4'] })).toEqual(['m-3', 'm-4'])
    expect(extractMessageIds({ message_id: 'm-5', id: 'other', message_ids: ['m-5', 'm-6', 'm-6'] })).toEqual(['m-5', 'm-6'])
    expect(extractMessageIds({ id: 'm-7', message_ids: ['m-7', 'm-8'] })).toEqual(['m-7', 'm-8'])
    expect(extractMessageIds('m-5')).toEqual(['m-5'])
    expect(extractMessageIds(null)).toEqual([])
  })
})

describe('createThrottledInvalidator', () => {
  it('invalidates the affected message detail on archive status events', () => {
    vi.useFakeTimers()
    const mockQc = { invalidateQueries: vi.fn() } as unknown as typeof queryClient
    const throttler = createThrottledInvalidator(mockQc, 100)

    throttler.handleEvent('archive.progress', {
      message_id: 'm-archive',
      message_ids: ['m-archive', 'm-archive-2'],
      state: 'archive_complete',
    })
    vi.advanceTimersByTime(100)

    expect(mockQc.invalidateQueries).toHaveBeenCalledTimes(2)
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['detail', 'mail-core', 'm-archive'] })
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['detail', 'mail-core', 'm-archive-2'] })
    vi.useRealTimers()
  })

  it('batches and throttles multiple rapid events within time window', () => {
    vi.useFakeTimers()
    const mockQc = {
      invalidateQueries: vi.fn(),
    } as unknown as typeof queryClient

    const throttler = createThrottledInvalidator(mockQc, 100)

    throttler.handleEvent('message.upserted', { message_id: 'id-1' })
    throttler.handleEvent('folder.stats_updated', {})
    throttler.handleEvent('message.upserted', { message_id: 'id-2' })
    throttler.handleEvent('message.upserted', { message_id: 'id-1' })

    expect(mockQc.invalidateQueries).not.toHaveBeenCalled()

    vi.advanceTimersByTime(100)

    // List and stats caches are invalidated separately; details for id-1 and id-2 once each.
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['detail', 'mail-core', 'id-1'] })
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['detail', 'mail-core', 'id-2'] })
    expect(mockQc.invalidateQueries).toHaveBeenCalledTimes(4)

    const invalidations = (mockQc.invalidateQueries as unknown as ReturnType<typeof vi.fn>).mock.calls
      .map(([options]) => options as { predicate?: (query: unknown) => boolean })
    const listPredicate = invalidations.find((options) =>
      options.predicate?.({ queryKey: ['mail-core', 'inbox', 'all'] }))?.predicate
    const statsPredicate = invalidations.find((options) =>
      options.predicate?.({ queryKey: ['mail-core', 'stats'] }))?.predicate

    expect(listPredicate).toBeDefined()
    expect(listPredicate?.({ queryKey: ['mail-core', 'account-folders', 'account-1'] })).toBe(false)
    expect(listPredicate?.({ queryKey: ['mail-core', 'stats'] })).toBe(false)
    expect(statsPredicate).toBeDefined()
    expect(statsPredicate?.({ queryKey: ['mail-core', 'folder-stats', 'all', 'inbox', ''] })).toBe(true)
    expect(statsPredicate?.({ queryKey: ['mail-core', 'inbox', 'all'] })).toBe(false)

    vi.useRealTimers()
  })

  it('refreshes organization and aggregate caches after an account is enabled or disabled', async () => {
    vi.useFakeTimers()
    const mockQc = { invalidateQueries: vi.fn() } as unknown as typeof queryClient
    const throttler = createThrottledInvalidator(mockQc, 100)
    throttler.handleEvent('account.updated', { sync_enabled: false })
    await vi.advanceTimersByTimeAsync(100)

    const calls = (mockQc.invalidateQueries as unknown as ReturnType<typeof vi.fn>).mock.calls.map(([arg]) => arg)
    expect(calls).toHaveLength(5)
    expect(calls).toContainEqual({ queryKey: ['accounts'] })
    expect(calls).toContainEqual({ queryKey: ['groups'] })
    expect(calls).toContainEqual({ queryKey: ['sidebar-layout'] })
    expect(calls.some((arg) => (arg as { predicate?: unknown }).predicate)).toBe(true)
    vi.useRealTimers()
  })

  it('defers SSE list and stats invalidation until an optimistic read settles', async () => {
    queryClient.clear()
    const message: MailItem = {
      id: 'read-1', subject: 'S', from: 'a@b.c', is_read: false, is_flagged: false,
      has_attachments: false, accountEmail: 'acc@x.test', accountId: 'acc-1',
      locations: [{ folder_id: 'inbox-1', role: 'inbox' }],
    }
    queryClient.setQueryData(queryKeys.inbox(), [message])
    queryClient.setQueryData(queryKeys.stats, { totalUnread: 1, byAccount: new Map([['acc-1', 1]]) })
    let releaseRead!: () => void
    let readStarted!: () => void
    const started = new Promise<void>((resolve) => { readStarted = resolve })
    const gate = new Promise<void>((resolve) => { releaseRead = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/api/auth/me')) return new Response(JSON.stringify({ csrf_token: 'test' }), { status: 200 })
      if (url.endsWith('/messages/read-1/read')) {
        readStarted()
        await gate
        return new Response(JSON.stringify({ id: 'read-1', is_read: true }), { status: 200 })
      }
      return new Response(JSON.stringify({ detail: 'unexpected' }), { status: 404 })
    }))
    const mutation = setReadOptimistic([message], true)
    await started

    const throttler = createThrottledInvalidator(queryClient, 0)
    throttler.handleEvent('folder.stats_updated', {})
    throttler.flush()
    expect(queryClient.getQueryState(queryKeys.inbox())?.isInvalidated).toBe(false)
    expect(queryClient.getQueryState(queryKeys.stats)?.isInvalidated).toBe(false)

    releaseRead()
    await mutation
    expect(queryClient.getQueryState(queryKeys.inbox())?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(queryKeys.stats)?.isInvalidated).toBe(true)
    throttler.cancel()
    queryClient.clear()
    vi.unstubAllGlobals()
  })
})

describe('useMailCoreRealtime unauthorized handling', () => {
  it('dispatches UNAUTHORIZED_EVENT on 401/403 status', async () => {
    let capturedOptions: sseModule.SseStreamOptions | undefined
    vi.spyOn(sseModule, 'subscribeMailCoreStream').mockImplementation((_onEvent, options) => {
      capturedOptions = options
      return () => {}
    })

    const listener = vi.fn()
    window.addEventListener(UNAUTHORIZED_EVENT, listener)

    function TestComp() {
      useMailCoreRealtime(true)
      return null
    }

    await render(createElement(TestComp))

    expect(capturedOptions?.onUnauthorized).toBeDefined()
    capturedOptions!.onUnauthorized!(401)

    expect(listener).toHaveBeenCalledTimes(1)

    window.removeEventListener(UNAUTHORIZED_EVENT, listener)
    cleanup()
    vi.restoreAllMocks()
  })
})
