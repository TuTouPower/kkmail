import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, api } from './client'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

function stubLoginFlow(meResponse: () => Response) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).endsWith('/api/auth/login')) return json(200, { csrf_token: 'tok-login' })
    if (String(url).endsWith('/api/auth/me')) return meResponse()
    throw new Error(`unexpected fetch ${url}`)
  }))
}

describe('login session establishment verification (t079)', () => {
  it('resolves when the post-login /me verification succeeds', async () => {
    stubLoginFlow(() => json(200, { csrf_token: 'tok-me' }))
    await expect(api.login('correct horse battery staple')).resolves.toBeUndefined()
  })

  it('rejects with a named session_not_established error when /me answers 401 after a successful login', async () => {
    stubLoginFlow(() => json(401, { detail: 'unauthorized' }))
    const err = await api.login('correct horse battery staple').catch((e: unknown) => e) as { code?: string; message?: string }
    expect(err.code).toBe('session_not_established')
    expect(err.message).toBeTruthy()
  })

  it('rejects with session_not_established when the verification request itself fails', async () => {
    stubLoginFlow(() => json(500, { detail: 'boom' }))
    await expect(api.login('correct horse battery staple')).rejects.toMatchObject({
      code: 'session_not_established',
    })
  })

  it('checkSession still returns false silently on a cold-start 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(401, { detail: 'unauthorized' })))
    await expect(api.checkSession()).resolves.toBe(false)
  })


  it('bounds the /me verification by the caller timeout (t079 code f001)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith('/api/auth/login')) return json(200, { csrf_token: 'tok' })
      if (String(url).endsWith('/api/auth/me')) {
        // Model real fetch: settles only when the request signal aborts.
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('aborted')))
        })
      }
      throw new Error(`unexpected fetch ${url}`)
    }))
    // The caller's budget governs the whole login, verification included:
    // exhausting it surfaces the same 'timeout' error as a slow POST leg.
    // (A verification failure *within* budget is session_not_established,
    // covered by the two cases above.)
    await expect(api.login('correct horse battery staple', { timeoutMs: 50 })).rejects.toMatchObject({
      code: 'timeout',
    })
  })
})
