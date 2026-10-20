import { describe, expect, it } from 'vitest'
import { canSendFrom } from './accounts'

describe('canSendFrom', () => {
  it('defaults to false', () => {
    expect(canSendFrom(null)).toBe(false)
    expect(canSendFrom(undefined)).toBe(false)
    expect(canSendFrom({})).toBe(false)
  })

  it('requires outlook/graph and authorized status', () => {
    expect(canSendFrom({ provider: 'graph', status: 'authorized' })).toBe(true)
    expect(canSendFrom({ provider: 'outlook', status: 'authorized' })).toBe(true)
    expect(canSendFrom({ account_type: 'graph', status: 'authorized' })).toBe(true)
    expect(canSendFrom({ provider: 'graph', status: 'active' })).toBe(false)
    expect(canSendFrom({ provider: 'imap', status: 'authorized' })).toBe(false)
    expect(canSendFrom({ provider: 'gmail', status: 'authorized' })).toBe(false)
  })
})
