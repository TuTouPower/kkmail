// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { parseSseChunk, subscribeMailCoreStream, type SseParserState } from './sseStream'

describe('parseSseChunk', () => {
  it('parses standard SSE events and normalizes JSON payloads', () => {
    const events: Array<{ event: string; data: unknown; id: string | null }> = []
    const state: SseParserState = {
      buffer: '',
      eventName: 'message',
      dataBuffer: [],
      lastEventId: null,
    }

    parseSseChunk(
      'event: message.upserted\nid: ev-1\ndata: {"id":"m1"}\n\n:ping\nevent: custom\ndata: raw string\n\n',
      state,
      (event, data, id) => {
        events.push({ event, data, id })
      },
    )

    expect(events).toEqual([
      { event: 'message.upserted', data: { id: 'm1' }, id: 'ev-1' },
      { event: 'custom', data: 'raw string', id: 'ev-1' },
    ])
  })

  it('handles chunks split across lines and multiline data correctly', () => {
    const events: Array<{ event: string; data: unknown; id: string | null }> = []
    const state: SseParserState = {
      buffer: '',
      eventName: 'message',
      dataBuffer: [],
      lastEventId: null,
    }

    parseSseChunk('data: line 1\n', state, (event, data, id) => events.push({ event, data, id }))
    expect(events).toHaveLength(0)

    parseSseChunk('data: line 2\n\n', state, (event, data, id) => events.push({ event, data, id }))
    expect(events).toEqual([{ event: 'message', data: 'line 1\nline 2', id: null }])
  })
})

describe('subscribeMailCoreStream', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function mockSseResponse(bodyText: string, status = 200) {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(bodyText))
        controller.close()
      },
    })
    return new Response(stream, {
      status,
      headers: { 'Content-Type': 'text/event-stream' },
    })
  }

  it('connects with credentials and sends custom headers and Last-Event-ID', async () => {
    let capturedInit: RequestInit | undefined
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      capturedInit = init
      return mockSseResponse('id: 101\nevent: test\ndata: {"ok":true}\n\n')
    }))

    const onEvent = vi.fn()
    const onOpen = vi.fn()

    const unsubscribe = subscribeMailCoreStream(onEvent, {
      headers: { 'X-Custom-Auth': 'token-123' },
      initialLastEventId: '99',
      onOpen,
    })

    // Allow fetch microtask to resolve
    await vi.advanceTimersByTimeAsync(10)

    expect(capturedInit?.credentials).toBe('include')
    const headers = capturedInit?.headers as Record<string, string>
    expect(headers['X-Custom-Auth']).toBe('token-123')
    expect(headers['Last-Event-ID']).toBe('99')
    expect(onOpen).toHaveBeenCalled()
    expect(onEvent).toHaveBeenCalledWith('test', { ok: true }, '101')

    unsubscribe()
  })

  it('dispatches every named mail-core outbox event from the fetch stream', async () => {
    const eventTypes = [
      'message.upserted',
      'message.removed',
      'folder.stats_updated',
      'sync.progress',
      'sync.completed',
      'sync.error',
      'remote_operation.updated',
      'client.resync_hint',
    ]
    const body = eventTypes.map((event) => `event: ${event}\ndata: {}\n\n`).join('')
    vi.stubGlobal('fetch', vi.fn(async () => mockSseResponse(body)))
    const onEvent = vi.fn()

    const unsubscribe = subscribeMailCoreStream(onEvent)
    await vi.advanceTimersByTimeAsync(10)

    expect(onEvent.mock.calls.map(([event]) => event)).toEqual(eventTypes)
    unsubscribe()
  })

  it('stops reconnecting on 401/403 and fires onUnauthorized and unauthorized event', async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(JSON.stringify({ detail: 'unauthorized' }), { status: 401 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const onUnauthorized = vi.fn()
    const onEvent = vi.fn()

    const unsubscribe = subscribeMailCoreStream(onEvent, {
      onUnauthorized,
      retryIntervalMs: 500,
    })

    await vi.advanceTimersByTimeAsync(10)
    expect(onUnauthorized).toHaveBeenCalledWith(401)
    expect(onEvent).toHaveBeenCalledWith('unauthorized', { status: 401 }, null)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // Advance time past retry window - verify it did NOT retry
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    unsubscribe()
  })

  it('reconnects with updated Last-Event-ID on stream error or disconnect', async () => {
    let callCount = 0
    const capturedLastIds: Array<string | undefined> = []

    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      callCount++
      const headers = init?.headers as Record<string, string> | undefined
      capturedLastIds.push(headers?.['Last-Event-ID'])

      if (callCount === 1) {
        return mockSseResponse('id: msg-42\nevent: update\ndata: {}\n\n')
      }
      return mockSseResponse('id: msg-43\nevent: update2\ndata: {}\n\n')
    }))

    const onEvent = vi.fn()
    const onError = vi.fn()

    const unsubscribe = subscribeMailCoreStream(onEvent, {
      retryIntervalMs: 200,
      onError,
    })

    await vi.advanceTimersByTimeAsync(10)
    expect(onEvent).toHaveBeenCalledWith('update', {}, 'msg-42')
    expect(capturedLastIds[0]).toBeUndefined()

    // Trigger scheduled reconnect
    await vi.advanceTimersByTimeAsync(250)
    expect(callCount).toBe(2)
    expect(capturedLastIds[1]).toBe('msg-42')
    expect(onEvent).toHaveBeenCalledWith('update2', {}, 'msg-43')

    unsubscribe()
  })

  it('triggers visibility recovery callback on visibility change to visible', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      return mockSseResponse(':keepalive\n\n')
    }))

    const onVisibilityRecovery = vi.fn()
    const unsubscribe = subscribeMailCoreStream(vi.fn(), {
      onVisibilityRecovery,
    })

    await vi.advanceTimersByTimeAsync(10)

    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    })
    document.dispatchEvent(new Event('visibilitychange'))

    expect(onVisibilityRecovery).toHaveBeenCalled()

    unsubscribe()
  })
})
