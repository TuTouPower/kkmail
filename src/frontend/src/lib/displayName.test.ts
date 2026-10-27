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
  // t047 修复：发件人缺失时留白，不再返回“未知”
  it('returns empty string for empty or blank input (AC-002)', () => {
    expect(displayName('')).toBe('')
    expect(displayName('   ')).toBe('')
    expect(displayName(undefined)).toBe('')
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
  it('extracts the address token from a bare "Name addr@x" string', () => {
    expect(displayEmail('Alice Liddell alice@kkmail.test')).toBe('alice@kkmail.test')
    expect(displayEmail('"Alice Liddell" alice@kkmail.test')).toBe('alice@kkmail.test')
  })
  it('returns empty string when no token contains @', () => {
    expect(displayEmail('Alice Liddell')).toBe('')
  })
  it('returns empty string for empty input', () => {
    expect(displayEmail('')).toBe('')
    expect(displayEmail(undefined)).toBe('')
  })
})
