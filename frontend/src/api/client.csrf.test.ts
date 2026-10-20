import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, api } from './client'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

describe('CSRF handling', () => {
  it('refetches the token and retries once on a CSRF failure', async () => {
    const calls: Array<{ url: string; token?: string }> = []
    let tokenN = 0
    let posts = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const h = (init.headers || {}) as Record<string, string>
      calls.push({ url, token: h['X-CSRFToken'] })
      if (url === '/api/csrf-token') return json(200, { csrf_token: `tok${++tokenN}` })
      posts += 1
      if (posts === 1) return json(400, { success: false, error: 'CSRF 校验失败，请刷新页面后重试', csrf_error: true })
      return json(200, { success: true })
    }))
    const res = await api.markRead({ email: 'a@x', items: [{ id: '1' }] })
    expect(res).toEqual({ success: true })
    const writes = calls.filter((c) => c.url === '/api/emails/mark-read')
    expect(writes.map((c) => c.token)).toEqual(['tok1', 'tok2'])
  })

  it('does not loop when the retry also fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/csrf-token') return json(200, { csrf_token: 't' })
      return json(400, { success: false, error: 'CSRF 校验失败', csrf_error: true })
    }))
    await expect(api.markRead({ email: 'a@x', items: [{ id: '1' }] })).rejects.toMatchObject({ status: 400 })
    expect((fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(4)
  })

  it('times out slow requests with a clear error', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit = {}) => new Promise((_res, rej) => {
      init.signal?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
    })))
    await expect(api.getEmails('a@x', {}, { timeoutMs: 20 })).rejects.toMatchObject({ code: 'timeout' })
  })
})
