import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, apiRequest } from './client'

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
