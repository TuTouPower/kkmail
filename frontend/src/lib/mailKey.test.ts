import { describe, expect, it } from 'vitest'
import { hasMailId, mailKey } from './mailKey'

describe('mailKey', () => {
  it('is the mail-core message UUID', () => {
    expect(mailKey({ id: '0b6f2c1e-1111-4222-8333-944455556666' })).toBe('0b6f2c1e-1111-4222-8333-944455556666')
  })

  it('rejects empty ids so they cannot collide as React keys', () => {
    expect(() => mailKey({ id: '' })).toThrow(/non-empty/)
    expect(() => mailKey({ id: '   ' })).toThrow(/non-empty/)
  })

  it('hasMailId filters blanks', () => {
    expect(hasMailId({ id: 'x' })).toBe(true)
    expect(hasMailId({ id: '' })).toBe(false)
    expect(hasMailId({ id: null })).toBe(false)
  })
})
