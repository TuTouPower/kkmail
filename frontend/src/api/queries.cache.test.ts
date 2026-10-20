import { describe, expect, it } from 'vitest'
import { MAIL_STALE_TIME_MS, queryClient } from './queries'

describe('mail list cache policy', () => {
  it('keeps lists fresh for several minutes', () => {
    expect(MAIL_STALE_TIME_MS).toBeGreaterThanOrEqual(5 * 60_000)
    expect(queryClient.getDefaultOptions().queries?.staleTime).toBe(MAIL_STALE_TIME_MS)
  })
})
