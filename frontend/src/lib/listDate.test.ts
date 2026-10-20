import { describe, expect, it } from 'vitest'
import { formatListDate, formatReaderDate } from './listDate'

describe('formatListDate', () => {
  const now = Date.parse('2026-10-20T21:00:00+08:00')
  it('shows HH:mm within one day', () => {
    expect(formatListDate('2026-10-20T15:30:00+08:00', now)).toMatch(/15:30/)
  })
  it('shows weekday + date when older than one day', () => {
    const out = formatListDate('2026-10-16T10:00:00+08:00', now)
    expect(out).toMatch(/10/)
    expect(out).toMatch(/16/)
    expect(out).not.toMatch(/:/)
  })
})

describe('formatReaderDate', () => {
  it('returns a short localized datetime', () => {
    const out = formatReaderDate('Thu, 15 Oct 2026 19:48:50 +0000')
    expect(out).toMatch(/2026/)
    expect(out).not.toMatch(/UTC/)
    expect(out).not.toMatch(/\+0000/)
  })
})
