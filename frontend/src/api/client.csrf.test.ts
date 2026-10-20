import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, api, apiRequest, postJson } from './client'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

describe('CSRF handling', () => {
  it('fetches a token, sends it, and retries once on a CSRF 403', async () => {
    const tokens: Array<string | undefined> = []
    let tokenN = 0
    let posts = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      if (String(url).endsWith('/api/auth/me')) return json(200, { csrf_token: `tok${++tokenN}`, via: 'session' })
      tokens.push(((init.headers || {}) as Record<string, string>)['X-CSRF-Token'])
      posts += 1
      if (posts === 1) return json(403, { detail: { error: 'CSRF validation failed', csrf_error: true } })
      return json(200, { id: '1', is_read: true })
    }))
    const res = await postJson<{ is_read: boolean }>('/api/mail/messages/1/read', { is_read: true })
    expect(res.is_read).toBe(true)
    expect(tokens).toEqual(['tok1', 'tok2'])
  })

  it('does not loop when the retry also fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).endsWith('/api/auth/me')) return json(200, { csrf_token: 't' })
      return json(403, { detail: { error: 'CSRF validation failed', csrf_error: true } })
    }))
    await expect(postJson('/api/mail/messages/1/read', { is_read: true })).rejects.toMatchObject({
      status: 403,
      message: 'CSRF validation failed',
    })
    // me + write + me + write
    expect((fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(4)
  })

  it('never sends an unsafe request when no CSRF token can be obtained', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).endsWith('/api/auth/me')) return json(401, { detail: 'authentication required' })
      return json(200, {})
    })
    vi.stubGlobal('fetch', fetchMock)
    await expect(postJson('/api/mail/messages/1/trash')).rejects.toMatchObject({ code: 'csrf_unavailable' })
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toEqual(['/api/auth/me'])
  })

  it('GET requests need no CSRF token', async () => {
    const fetchMock = vi.fn(async () => json(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    await apiRequest('/api/groups')
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('coalesces concurrent CSRF fetches (singleflight)', async () => {
    let meCalls = 0
    let release!: (v: Response) => void
    const gate = new Promise<Response>((resolve) => { release = resolve })
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      if (String(url).endsWith('/api/auth/me')) {
        meCalls += 1
        return gate
      }
      return json(200, { ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)
    const a = postJson('/api/mail/messages/1/flag', { is_flagged: true })
    const b = postJson('/api/mail/messages/2/flag', { is_flagged: true })
    // Allow microtasks to start both requests and share one /me
    await Promise.resolve()
    expect(meCalls).toBe(1)
    release(json(200, { csrf_token: 'shared' }))
    await Promise.all([a, b])
    expect(meCalls).toBe(1)
    const writeCalls = fetchMock.mock.calls.filter((c) => !String(c[0]).endsWith('/api/auth/me'))
    expect(writeCalls).toHaveLength(2)
    for (const [, init] of writeCalls) {
      expect(((init?.headers || {}) as Record<string, string>)['X-CSRF-Token']).toBe('shared')
    }
  })
})

describe('errors and timeouts', () => {
  it('times out slow requests with a clear error', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit = {}) => new Promise((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    await expect(apiRequest('/api/groups', { timeoutMs: 20 })).rejects.toMatchObject({ code: 'timeout' })
  })

  it('times out a hung body parse after headers arrive', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 200,
      statusText: 'OK',
      ok: true,
      headers: { get: () => 'application/json' },
      json: () => new Promise(() => { /* never settles */ }),
      text: () => new Promise(() => { /* never settles */ }),
    })))
    await expect(apiRequest('/api/groups', { timeoutMs: 30 })).rejects.toMatchObject({ code: 'timeout' })
  })

  it('surfaces FastAPI detail strings and validation errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(404, { detail: 'message not found' })))
    await expect(apiRequest('/api/mail/messages/x')).rejects.toMatchObject({ status: 404, message: 'message not found' })
    vi.stubGlobal('fetch', vi.fn(async () => json(422, { detail: [{ loc: ['body', 'is_read'], msg: 'Field required' }] })))
    await expect(apiRequest('/api/mail/messages/x')).rejects.toMatchObject({ status: 422, message: 'Field required' })
  })

  it('401 dispatches the unauthorized event', async () => {
    const seen = vi.fn()
    const target = new EventTarget()
    vi.stubGlobal('window', Object.assign(target, { location: { assign: vi.fn() } }))
    window.addEventListener('kkmail:unauthorized', seen)
    vi.stubGlobal('fetch', vi.fn(async () => json(401, { detail: 'authentication required' })))
    await expect(apiRequest('/api/groups')).rejects.toMatchObject({ status: 401 })
    expect(seen).toHaveBeenCalledOnce()
  })

  it('times out hung CSRF fetch during unsafe requests', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit = {}) => new Promise((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    await expect(postJson('/api/mail/messages/1/trash', {}, { timeoutMs: 30 })).rejects.toMatchObject({
      code: 'csrf_unavailable',
    })
  })

  it('times out hung login requests', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit = {}) => new Promise((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    await expect(api.login('secret', { timeoutMs: 30 })).rejects.toMatchObject({
      code: 'timeout',
    })
  })
})
