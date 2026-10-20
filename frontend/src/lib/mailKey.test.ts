import { describe, expect, it } from 'vitest'
import { mailKey } from './mailKey'

describe('mailKey', () => {
  it('is the mail-core message UUID', () => {
    expect(mailKey({ id: '0b6f2c1e-1111-4222-8333-944455556666' })).toBe('0b6f2c1e-1111-4222-8333-944455556666')
  })
})
