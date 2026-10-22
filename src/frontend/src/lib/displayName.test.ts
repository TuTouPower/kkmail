import { describe, expect, it } from 'vitest'
import { displayEmail, displayName } from './displayName'

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

describe('displayEmail', () => {
  it('extracts email address from angled format', () => {
    expect(displayEmail('ChatGPT <noreply@email.openai.com>')).toBe('noreply@email.openai.com')
    expect(displayEmail('"Apple" <noreply@email.apple.com>')).toBe('noreply@email.apple.com')
  })
  it('returns plain address if no angle brackets', () => {
    expect(displayEmail('alice@kkmail.test')).toBe('alice@kkmail.test')
  })
  it('returns empty string for empty input', () => {
    expect(displayEmail('')).toBe('')
    expect(displayEmail(undefined)).toBe('')
  })
})
