// @vitest-environment jsdom
import { createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { createThrottledInvalidator, extractMessageIds, shouldInvalidateMailCoreInbox, useMailCoreRealtime } from './useMailCoreRealtime'
import type { queryClient } from '../api/queries'
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
    expect(extractMessageIds('m-5')).toEqual(['m-5'])
    expect(extractMessageIds(null)).toEqual([])
  })
})

describe('createThrottledInvalidator', () => {
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

    // Should invalidate ['mail-core'] once, and details for id-1 and id-2 once each
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['mail-core'] })
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['detail', 'mail-core', 'id-1'] })
    expect(mockQc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['detail', 'mail-core', 'id-2'] })
    expect(mockQc.invalidateQueries).toHaveBeenCalledTimes(3)

    vi.useRealTimers()
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
