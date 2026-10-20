import { describe, expect, it } from 'vitest'
import { canSendFrom, importFormatHint } from './accounts'

describe('accounts helpers', () => {
  it('allows Outlook and rejects IMAP accounts for sending', () => {
    expect(canSendFrom({ account_type: 'outlook' })).toBe(true)
    expect(canSendFrom({ account_type: 'IMAP' })).toBe(false)
    expect(canSendFrom(undefined)).toBe(false)
  })

  it('gives a per-provider import format', () => {
    expect(importFormatHint('outlook').placeholder).toContain('refresh_token')
    expect(importFormatHint('custom').placeholder).toContain('993')
    expect(importFormatHint('qq').help).toContain('授权码')
  })
})
