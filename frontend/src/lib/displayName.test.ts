import { describe, expect, it } from 'vitest'
import { displayName } from './displayName'

describe('displayName', () => {
  it('prefers the display name over the address', () => {
    expect(displayName('ChatGPT <noreply@email.openai.com>')).toBe('ChatGPT')
    expect(displayName('"Apple" <noreply@email.apple.com>')).toBe('Apple')
  })
  it('falls back to the local part for bare addresses', () => {
    expect(displayName('alice@kkmail.test')).toBe('alice')
  })
  it('returns 未知 for empty input', () => {
    expect(displayName('')).toBe('未知')
    expect(displayName(undefined)).toBe('未知')
  })
})
