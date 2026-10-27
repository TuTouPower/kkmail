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
      retryMs: null,
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

  it('keeps the latest valid retry directive and ignores invalid values', () => {
    const state: SseParserState = {
      buffer: '',
      eventName: 'message',
      dataBuffer: [],
      lastEventId: null,
      retryMs: null,
    }

    parseSseChunk('retry: 2500\nretry: 3 seconds\nretry: -1\n\n', state, vi.fn())
    expect(state.retryMs).toBe(2500)

    parseSseChunk('retry: 4000\n\n', state, vi.fn())
    expect(state.retryMs).toBe(4000)
  })

  it('handles chunks split across lines and multiline data correctly', () => {
    const events: Array<{ event: string; data: unknown; id: string | null }> = []
    const state: SseParserState = {
      buffer: '',
      eventName: 'message',
      dataBuffer: [],
      lastEventId: null,
      retryMs: null,
    }

    parseSseChunk('data: line 1\n', state, (event, data, id) => events.push({ event, data, id }))
    expect(events).toHaveLength(0)

    parseSseChunk('data: line 2\n\n', state, (event, data, id) => events.push({ event, data, id }))
    expect(events).toEqual([{ event: 'message', data: 'line 1\nline 2', id: null }])
  })

  it('does not dispatch a named event without data but keeps explicit empty data', () => {
    const state: SseParserState = {
      buffer: '',
      eventName: 'message',
      dataBuffer: [],
      lastEventId: null,
      retryMs: null,
    }
    const onEvent = vi.fn()

    parseSseChunk('id: ev-2\nevent: named\n\n', state, onEvent)
    expect(onEvent).not.toHaveBeenCalled()
    expect(state.eventName).toBe('message')
    expect(state.lastEventId).toBe('ev-2')

    parseSseChunk('event: empty-data\ndata:\n\n', state, onEvent)
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenCalledWith('empty-data', '', 'ev-2')
  })
})

describe('subscribeMailCoreStream', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
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

  it('backs off exponentially with jitter and resets after a successful open', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockRejectedValueOnce(new Error('offline'))
      .mockImplementation(async () => mockSseResponse(':keepalive\n\n'))
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(Math, 'random').mockReturnValue(0.5)

    const unsubscribe = subscribeMailCoreStream(vi.fn())
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1089)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(2199)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(3)

    await vi.advanceTimersByTimeAsync(1099)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(4)

    unsubscribe()
  })

  it('caps exponential reconnect delay at 30 seconds', async () => {
    const fetchMock = vi.fn(async () => { throw new Error('offline') })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(Math, 'random').mockReturnValue(0.5)

    const unsubscribe = subscribeMailCoreStream(vi.fn())
    await vi.advanceTimersByTimeAsync(10)
    const delays = [1100, 2200, 4400, 8800, 17600, 30000]

    for (const [index, delay] of delays.entries()) {
      const remaining = delay - (index === 0 ? 10 : 0)
      await vi.advanceTimersByTimeAsync(remaining - 1)
      expect(fetchMock).toHaveBeenCalledTimes(index + 1)
      await vi.advanceTimersByTimeAsync(1)
      expect(fetchMock).toHaveBeenCalledTimes(index + 2)
    }

    unsubscribe()
  })

  it('uses the server retry directive as the reconnect delay', async () => {
    const fetchMock = vi.fn(async () => mockSseResponse('retry: 5000\n\n'))
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(Math, 'random').mockReturnValue(0)

    const unsubscribe = subscribeMailCoreStream(vi.fn())
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(4989)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    unsubscribe()
  })

  it('dispatches every named mail-core outbox event from the fetch stream', async () => {
    const eventTypes = [
      'account.updated',
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

  it('aborts and reconnects when the stream receives no bytes for two keepalive intervals', async () => {
    const firstSignals: AbortSignal[] = []
    let streamCancelled = false
    let fetchCount = 0
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      fetchCount++
      if (fetchCount > 1) {
        return mockSseResponse(': keepalive\n\n')
      }
      firstSignals.push(init?.signal as AbortSignal)
      const body = new ReadableStream<Uint8Array>({
        cancel() {
          streamCancelled = true
        },
      })
      return new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const onError = vi.fn()
    const unsubscribe = subscribeMailCoreStream(vi.fn(), { retryIntervalMs: 1000, onError })

    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(29_989)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(11)
    expect(firstSignals[0]?.aborted).toBe(true)
    expect(streamCancelled).toBe(true)
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'SSE stream idle timeout' }))

    await vi.advanceTimersByTimeAsync(900)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(100)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    unsubscribe()
  })

  it('resets the stale timeout when keepalive bytes continue arriving', async () => {
    const encoder = new TextEncoder()
    let keepaliveTimer: ReturnType<typeof setInterval> | null = null
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        keepaliveTimer = setInterval(() => {
          controller.enqueue(encoder.encode(': keepalive\n\n'))
        }, 10_000)
      },
      cancel() {
        if (keepaliveTimer !== null) clearInterval(keepaliveTimer)
      },
    })
    const fetchMock = vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const unsubscribe = subscribeMailCoreStream(vi.fn())

    await vi.advanceTimersByTimeAsync(10)
    await vi.advanceTimersByTimeAsync(50_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    unsubscribe()
  })

  it('honours a server retry directive below the default 1000ms floor (A299)', async () => {
    const fetchMock = vi.fn(async () => mockSseResponse('retry: 200\n\n'))
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(Math, 'random').mockReturnValue(0)

    const unsubscribe = subscribeMailCoreStream(vi.fn())
    await vi.advanceTimersByTimeAsync(10)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(189)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    unsubscribe()
  })

  it('flushes the TextDecoder when the stream ends (A299)', async () => {
    let flushCalls = 0
    class CountingDecoder extends TextDecoder {
      override decode(input?: BufferSource, options?: TextDecodeOptions): string {
        if (input === undefined) flushCalls += 1
        return super.decode(input, options)
      }
    }
    vi.stubGlobal('TextDecoder', CountingDecoder)
    vi.stubGlobal('fetch', vi.fn(async () => mockSseResponse('event: test\ndata: {"ok":true}\n\n')))
    const onEvent = vi.fn()

    const unsubscribe = subscribeMailCoreStream(onEvent)
    await vi.advanceTimersByTimeAsync(10)

    expect(onEvent).toHaveBeenCalledWith('test', { ok: true }, null)
    expect(flushCalls).toBeGreaterThan(0)

    unsubscribe()
  })

  it('removes the external abort listener on unsubscribe (A276)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => mockSseResponse(':keepalive\n\n')))
    const controller = new AbortController()
    const addSpy = vi.spyOn(controller.signal, 'addEventListener')
    const removeSpy = vi.spyOn(controller.signal, 'removeEventListener')

    const unsubscribe = subscribeMailCoreStream(vi.fn(), { signal: controller.signal })
    await vi.advanceTimersByTimeAsync(10)

    const added = addSpy.mock.calls.find(([type]) => type === 'abort')
    expect(added).toBeDefined()

    unsubscribe()

    const removed = removeSpy.mock.calls.find(([type]) => type === 'abort')
    expect(removed).toBeDefined()
    expect(removed?.[1]).toBe(added?.[1])
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
