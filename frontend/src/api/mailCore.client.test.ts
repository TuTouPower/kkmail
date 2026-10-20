import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, apiRequest, postJson, UNAUTHORIZED_EVENT } from './client'
import {
  fetchMailCoreMessage,
  mailCoreAttachmentUrl,
  mailCoreToMailDetail,
  mailCoreToMailItem,
  MAIL_CORE_EVENTS,
  postMailCoreMessageTrash,
  subscribeMailCoreEvents,
  type MailCoreMessage,
  type MailCoreMessageDetail,
} from './mailCore'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

type Call = [string, RequestInit]
function calls(mock: { mock: { calls: unknown[][] } }): Call[] {
  return mock.mock.calls as unknown as Call[]
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  __resetCsrfForTests()
})

describe('transport', () => {
  it('always sends the session cookie and JSON Accept header', async () => {
    const mock = vi.fn(async () => json(200, { items: [], next_cursor: null }))
    vi.stubGlobal('fetch', mock)
    await apiRequest('/api/mail/inbox?limit=1')
    const [, init] = calls(mock)[0]
    expect(init.credentials).toBe('include')
    expect(init.method).toBe('GET')
    expect((init.headers as Record<string, string>).Accept).toBe('application/json')
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
  })

  it('reuses a cached CSRF token across writes', async () => {
    const mock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/auth/me')) return json(200, { csrf_token: 'tok' })
      return json(200, { id: 'm', account_id: 'a', operation_id: 'o', success: true })
    })
    vi.stubGlobal('fetch', mock)
    await postMailCoreMessageTrash('m')
    await postMailCoreMessageTrash('m')
    const urls = calls(mock).map(([u]) => u)
    expect(urls).toEqual(['/api/auth/me', '/api/mail/messages/m/trash', '/api/mail/messages/m/trash'])
    for (const [, init] of calls(mock).slice(1)) {
      expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok')
      expect(init.method).toBe('POST')
      expect(init.body).toBe('{}')
    }
  })

  it('a 401 clears the CSRF token so the next write fetches a fresh one', async () => {
    vi.stubGlobal('window', Object.assign(new EventTarget(), { location: { assign: vi.fn() } }))
    let meCalls = 0
    let writes = 0
    const mock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/auth/me')) return json(200, { csrf_token: `tok${++meCalls}` })
      writes += 1
      if (writes === 1) return json(401, { detail: 'authentication required' })
      return json(200, { ok: true })
    })
    vi.stubGlobal('fetch', mock)
    await expect(postJson('/api/auth/logout')).rejects.toMatchObject({ status: 401, code: 'unauthorized' })
    await postJson('/api/auth/logout')
    const sent = calls(mock)
      .filter(([u]) => !u.endsWith('/api/auth/me'))
      .map(([, init]) => (init.headers as Record<string, string>)['X-CSRF-Token'])
    expect(sent).toEqual(['tok1', 'tok2'])
  })

  it('a 401 on a read dispatches the unauthorized event exactly once and does not retry', async () => {
    const target = Object.assign(new EventTarget(), { location: { assign: vi.fn() } })
    vi.stubGlobal('window', target)
    const seen = vi.fn()
    target.addEventListener(UNAUTHORIZED_EVENT, seen)
    const mock = vi.fn(async () => json(401, { detail: 'authentication required' }))
    vi.stubGlobal('fetch', mock)
    await expect(fetchMailCoreMessage('m1')).rejects.toMatchObject({ status: 401, message: '登录已过期，请重新登录' })
    expect(mock).toHaveBeenCalledOnce()
    expect(seen).toHaveBeenCalledOnce()
  })

  it('a caller abort is rethrown as-is, not reported as a timeout', async () => {
    vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit = {}) => new Promise((_r, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    const ctrl = new AbortController()
    const p = apiRequest('/api/mail/inbox', { signal: ctrl.signal, timeoutMs: 10_000 })
    ctrl.abort()
    await expect(p).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('an already-aborted caller signal aborts immediately', async () => {
    const mock = vi.fn((_u: string, init: RequestInit = {}) =>
      init.signal?.aborted ? Promise.reject(new DOMException('aborted', 'AbortError')) : Promise.resolve(json(200, {})),
    )
    vi.stubGlobal('fetch', mock)
    const ctrl = new AbortController()
    ctrl.abort()
    await expect(apiRequest('/api/groups', { signal: ctrl.signal })).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('times out with the default 30s budget', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit = {}) => new Promise((_r, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    const p = apiRequest('/api/groups')
    const assertion = expect(p).rejects.toMatchObject({ status: 0, code: 'timeout', message: '请求超时（30 秒）' })
    await vi.advanceTimersByTimeAsync(29_999)
    await vi.advanceTimersByTimeAsync(1)
    await assertion
  })

  it('falls back to the status text when the error body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' })))
    await expect(apiRequest('/api/groups')).rejects.toMatchObject({ status: 502, message: 'Bad Gateway', payload: null })
  })

  it('uses detail.error from object-shaped errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(409, { detail: { error: 'account exists' } })))
    await expect(apiRequest('/api/accounts')).rejects.toMatchObject({ status: 409, message: 'account exists' })
  })

  it('returns undefined for 204 and text for non-JSON success bodies', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/api/auth/me')) return json(200, { csrf_token: 't' })
      if (url.endsWith('/api/groups/g1')) return new Response(null, { status: 204 })
      return new Response('plain', { status: 200, headers: { 'Content-Type': 'text/plain' } })
    }))
    await expect(apiRequest('/api/groups/g1', { method: 'DELETE' })).resolves.toBeUndefined()
    await expect(apiRequest('/health')).resolves.toBe('plain')
  })
})

describe('mail endpoints', () => {
  it('encodes message ids in the path', async () => {
    const mock = vi.fn(async () => json(200, {}))
    vi.stubGlobal('fetch', mock)
    await fetchMailCoreMessage('a/b c')
    expect(calls(mock)[0][0]).toBe('/api/mail/messages/a%2Fb%20c')
  })

  it('builds attachment URLs by id only', () => {
    expect(mailCoreAttachmentUrl('att 1')).toBe('/api/mail/attachments/att%201')
  })

  it('maps a sender without a display name to the bare address', () => {
    const row: MailCoreMessage = {
      id: 'u', account_id: 'acc', account_email: null, subject: '', from_address: 'x@y.z', from_name: null,
      sort_time: '2024-01-01T00:00:00Z', is_read: true, is_flagged: false, has_attachments: false, snippet: null, folder_id: null,
    }
    expect(mailCoreToMailItem(row)).toEqual({
      id: 'u', subject: '', from: 'x@y.z', date: '2024-01-01T00:00:00Z', is_read: true, is_flagged: false,
      has_attachments: false, body_preview: undefined, folder: undefined, accountEmail: '', accountId: 'acc',
    })
  })

  it('maps empty bodies and optional attachment fields', () => {
    const d: MailCoreMessageDetail = {
      id: 'm', account_id: 'a', subject: 'S', from_address: 'a@b.c', from_name: null, from: 'a@b.c', to: '', cc: '',
      date: '2024-01-01T00:00:00Z', is_read: true, is_flagged: false, has_attachments: true, snippet: null, body: '',
      body_type: 'empty', parse_error: null,
      attachments: [{ id: 'att', name: 'a.pdf', contentType: null, size: null, is_inline: false }],
    }
    const out = mailCoreToMailDetail(d)
    expect(out.body_type).toBeUndefined()
    expect(out.cc).toBeUndefined()
    expect(out.attachments).toEqual([{ id: 'att', name: 'a.pdf', size: undefined, contentType: undefined }])
  })
})

describe('SSE subscription', () => {
  class FakeEventSource {
    static last: FakeEventSource | null = null
    listeners = new Map<string, EventListener>()
    onmessage: ((e: MessageEvent) => void) | null = null
    onerror: ((e: Event) => void) | null = null
    closed = false
    url: string
    init?: EventSourceInit
    constructor(url: string, init?: EventSourceInit) {
      this.url = url
      this.init = init
      FakeEventSource.last = this
    }
    addEventListener(name: string, fn: EventListener) {
      this.listeners.set(name, fn)
    }
    close() {
      this.closed = true
    }
  }

  it('uses cookie credentials, listens to every event type, parses JSON and closes', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const onEvent = vi.fn()
    const onError = vi.fn()
    const unsubscribe = subscribeMailCoreEvents(onEvent, onError)
    const es = FakeEventSource.last!
    expect(es.url).toBe('/api/events')
    expect(es.url).not.toContain('key')
    expect(es.init).toEqual({ withCredentials: true })
    expect([...es.listeners.keys()]).toEqual([...MAIL_CORE_EVENTS])
    expect(es.listeners.has('message')).toBe(false)
    expect(es.onmessage).toBeNull()

    es.listeners.get('message.upserted')!({ type: 'message.upserted', data: '{"id":"m1"}', lastEventId: '7' } as unknown as Event)
    es.listeners.get('sync.error')!({ type: 'sync.error', data: 'not json', lastEventId: '' } as unknown as Event)
    expect(onEvent.mock.calls).toEqual([
      ['message.upserted', { id: 'm1' }, '7'],
      ['sync.error', 'not json', null],
    ])

    const err = new Event('error')
    es.onerror!(err)
    expect(onError).toHaveBeenCalledWith(err)

    unsubscribe()
    expect(es.closed).toBe(true)
  })

  it('subscribes to the outbox event types the backend emits to clients', () => {
    expect([...MAIL_CORE_EVENTS].sort()).toEqual([
      'client.resync_hint',
      'folder.stats_updated',
      'message.removed',
      'message.upserted',
      'remote_operation.updated',
      'sync.completed',
      'sync.error',
      'sync.progress',
    ])
  })
})
