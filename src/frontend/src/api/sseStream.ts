/**
 * Modern SSE stream reader based on fetch + ReadableStream.
 * Handles parsing, reconnection with backoff, Last-Event-ID, custom headers,
 * 401/403 authorization terminal stop, and visibility change auto-recovery.
 */

import { apiBaseUrl } from '../lib/apiBase'

export interface SseParserState {
  buffer: string
  eventName: string
  dataBuffer: string[]
  lastEventId: string | null
  retryMs: number | null
}

export function parseSseChunk(
  chunk: string,
  state: SseParserState,
  onEvent: (event: string, data: unknown, id: string | null) => void,
): void {
  state.buffer += chunk

  let text = state.buffer
  let keepTrailingCr = false
  if (text.endsWith('\r')) {
    text = text.slice(0, -1)
    keepTrailingCr = true
  }

  const lines = text.split(/\r\n|\r|\n/)
  state.buffer = (lines.pop() ?? '') + (keepTrailingCr ? '\r' : '')

  for (const line of lines) {
    if (line === '') {
      if (state.dataBuffer.length > 0 || state.eventName !== 'message') {
        const rawData = state.dataBuffer.join('\n')
        let parsed: unknown = rawData
        try {
          parsed = JSON.parse(rawData)
        } catch {
          /* keep raw string */
        }
        onEvent(state.eventName || 'message', parsed, state.lastEventId)
      }
      state.eventName = 'message'
      state.dataBuffer = []
      continue
    }

    if (line.startsWith(':')) {
      // SSE comment / ping
      continue
    }

    let field: string
    let value: string
    const colonIdx = line.indexOf(':')
    if (colonIdx !== -1) {
      field = line.slice(0, colonIdx)
      value = line.slice(colonIdx + 1)
      if (value.startsWith(' ')) {
        value = value.slice(1)
      }
    } else {
      field = line
      value = ''
    }

    if (field === 'event') {
      state.eventName = value
    } else if (field === 'data') {
      state.dataBuffer.push(value)
    } else if (field === 'id') {
      if (!value.includes('\0')) {
        state.lastEventId = value
      }
    } else if (field === 'retry' && /^\d+$/.test(value)) {
      const retryMs = Number(value)
      if (Number.isSafeInteger(retryMs)) {
        state.retryMs = retryMs
      }
    }
  }
}

export interface SseStreamOptions {
  headers?: Record<string, string>
  onOpen?: (res: Response) => void
  onError?: (err: unknown) => void
  onUnauthorized?: (status: number) => void
  onVisibilityRecovery?: () => void
  initialLastEventId?: string | null
  retryIntervalMs?: number
  signal?: AbortSignal
}

const INITIAL_RETRY_MS = 1000
const MAX_RETRY_MS = 30_000
const RETRY_JITTER_RATIO = 0.2

export function subscribeMailCoreStream(
  handler: (event: string, data: unknown, id: string | null) => void,
  options: SseStreamOptions = {},
): () => void {
  let closed = false
  let isConnected = false
  let lastEventId: string | null = options.initialLastEventId ?? null
  let currentAbortController: AbortController | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  const initialRetryMs = Math.min(MAX_RETRY_MS, Math.max(1, options.retryIntervalMs ?? INITIAL_RETRY_MS))
  let nextRetryMs = initialRetryMs
  let serverRetryMs: number | null = null

  function scheduleReconnect(immediate = false) {
    if (closed || reconnectTimer !== null) return
    if (immediate) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        void connect()
      }, 0)
      return
    }

    const baseRetryMs = Math.min(MAX_RETRY_MS, Math.max(nextRetryMs, serverRetryMs ?? 0))
    const jitteredRetryMs = Math.min(
      MAX_RETRY_MS,
      Math.round(baseRetryMs * (1 + Math.random() * RETRY_JITTER_RATIO)),
    )
    nextRetryMs = Math.min(MAX_RETRY_MS, baseRetryMs * 2)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      void connect()
    }, jitteredRetryMs)
  }

  async function connect() {
    if (closed) return
    if (currentAbortController) {
      currentAbortController.abort()
    }
    const ac = new AbortController()
    currentAbortController = ac

    const reqHeaders: Record<string, string> = {
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
      ...options.headers,
    }
    if (lastEventId) {
      reqHeaders['Last-Event-ID'] = lastEventId
    }

    try {
      const res = await fetch(`${apiBaseUrl()}/api/events`, {
        method: 'GET',
        headers: reqHeaders,
        credentials: 'include',
        signal: ac.signal,
      })

      if (closed || ac.signal.aborted) return

      if (res.status === 401 || res.status === 403) {
        options.onUnauthorized?.(res.status)
        handler('unauthorized', { status: res.status }, lastEventId)
        closed = true
        return
      }

      if (!res.ok) {
        throw new Error(`SSE HTTP error: ${res.status} ${res.statusText}`)
      }

      if (!res.body) {
        throw new Error('ReadableStream not supported or empty body')
      }

      isConnected = true
      nextRetryMs = initialRetryMs
      options.onOpen?.(res)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      const parserState: SseParserState = {
        buffer: '',
        eventName: 'message',
        dataBuffer: [],
        lastEventId,
        retryMs: null,
      }

      try {
        while (!closed && !ac.signal.aborted) {
          const { done, value } = await reader.read()
          if (done) break
          if (value) {
            const chunk = decoder.decode(value, { stream: true })
            parseSseChunk(chunk, parserState, (event, data, id) => {
              if (id !== null) {
                lastEventId = id
              }
              handler(event, data, id)
            })
            if (parserState.retryMs !== null) {
              serverRetryMs = Math.min(MAX_RETRY_MS, Math.max(INITIAL_RETRY_MS, parserState.retryMs))
            }
          }
        }
      } finally {
        reader.releaseLock()
      }
    } catch (err: unknown) {
      if (closed || ac.signal.aborted) return
      options.onError?.(err)
    } finally {
      isConnected = false
    }

    if (!closed) {
      scheduleReconnect()
    }
  }

  void connect()

  const onVisibilityChange = () => {
    if (typeof document === 'undefined') return
    if (document.visibilityState === 'visible' && !closed) {
      options.onVisibilityRecovery?.()
      if (!isConnected) {
        if (reconnectTimer !== null) {
          clearTimeout(reconnectTimer)
          reconnectTimer = null
        }
        void connect()
      }
    }
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }

  const unsubscribe = () => {
    closed = true
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (currentAbortController) {
      currentAbortController.abort()
      currentAbortController = null
    }
  }

  if (options.signal) {
    if (options.signal.aborted) {
      unsubscribe()
    } else {
      options.signal.addEventListener('abort', () => unsubscribe(), { once: true })
    }
  }

  return unsubscribe
}
