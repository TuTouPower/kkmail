import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, api, apiRequest, isApiError, postJson } from './client'

function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

describe('structured error codes and Retry-After parsing (A59)', () => {
  it('passes detail.code through to ApiError.code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(409, {
      detail: { error: 'account already exists', code: 'account_conflict' },
    })))
    await expect(apiRequest('/api/accounts')).rejects.toMatchObject({
      status: 409,
      message: 'account already exists',
      code: 'account_conflict',
    })
  })

  it('passes detail.error_code through to ApiError.code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(429, {
      detail: { error: 'slow down', error_code: 'rate_limited' },
    })))
    await expect(apiRequest('/api/accounts')).rejects.toMatchObject({
      status: 429,
      message: 'slow down',
      code: 'rate_limited',
    })
  })

  it('parses an HTTP-date Retry-After header into seconds', async () => {
    const retryAt = new Date(Date.now() + 10_000).toUTCString()
    vi.stubGlobal('fetch', vi.fn(async () => json(429, { detail: 'poll interval has not elapsed' }, { 'Retry-After': retryAt })))
    const err = await apiRequest('/api/accounts/oauth/flows/device-flow/poll').catch((e: unknown) => e) as { retryAfterSeconds?: number }
    expect(err.retryAfterSeconds).toBeGreaterThanOrEqual(8)
    expect(err.retryAfterSeconds).toBeLessThanOrEqual(10)
  })

  it('ignores an unparseable Retry-After header', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(503, { detail: 'unavailable' }, { 'Retry-After': 'not-a-date' })))
    const err = await apiRequest('/api/accounts').catch((e: unknown) => e) as { retryAfterSeconds?: number }
    expect(err.retryAfterSeconds).toBeUndefined()
  })
})

describe('isApiError branding (A254)', () => {
  it('does not mistake a plain business object for an ApiError', () => {
    expect(isApiError({ status: 200, message: 'just a payload' })).toBe(false)
    expect(isApiError({ status: 500, message: 'impostor', code: 'fake' })).toBe(false)
    expect(isApiError(null)).toBe(false)
    expect(isApiError('error')).toBe(false)
  })

  it('recognizes errors produced by the client itself', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(404, { detail: 'message not found' })))
    const err = await apiRequest('/api/mail/messages/x').catch((e: unknown) => e)
    expect(isApiError(err)).toBe(true)
  })

  it('does not pass a foreign ApiError-shaped rejection through the CSRF fetch', async () => {
    const foreign = { status: 503, message: 'foreign object, not from this client' }
    vi.stubGlobal('fetch', vi.fn(async () => { throw foreign }))
    await expect(postJson('/api/mail/messages/1/trash')).rejects.toMatchObject({
      status: 0,
      code: 'network_error',
    })
  })
})

describe('logout outside a DOM environment (A90)', () => {
  it('completes logout without touching window when window is undefined', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).endsWith('/api/auth/me')) return json(200, { csrf_token: 'csrf' })
      return json(200, {})
    }))
    vi.stubGlobal('window', undefined)
    await expect(api.logout()).resolves.toBeUndefined()
  })
})
