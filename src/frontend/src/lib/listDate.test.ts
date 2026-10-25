import { describe, expect, it } from 'vitest'
import { formatListDate, formatReaderDate } from './listDate'

describe('formatListDate', () => {
  const now = Date.parse('2026-10-20T21:00:00+08:00')
  it('shows HH:mm within one day', () => {
    const input = '2026-10-20T15:30:00+08:00'
    const expected = new Date(input).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    const out = formatListDate(input, now)
    expect(out).toMatch(/^\d{2}:\d{2}$/)
    expect(out).toBe(expected)
  })
  it('shows weekday + date when older than one day', () => {
    const input = '2026-10-16T10:00:00+08:00'
    const out = formatListDate(input, now)
    const d = new Date(input)
    expect(out).toContain(String(d.getMonth() + 1))
    expect(out).toContain(String(d.getDate()))
    expect(out).not.toMatch(/:/)
  })
  it('shows no date text for an unknown date', () => {
    expect(formatListDate(null, now)).toBe('')
  })
  it('shows no date text for an unparseable date', () => {
    expect(formatListDate('not-a-date', now)).toBe('')
  })
})

describe('formatReaderDate', () => {
  it('returns a short localized datetime', () => {
    const out = formatReaderDate('Thu, 15 Oct 2026 19:48:50 +0000')
    expect(out).toMatch(/2026/)
    expect(out).not.toMatch(/UTC/)
    expect(out).not.toMatch(/\+0000/)
  })
  it('shows no date text for an unknown date', () => {
    expect(formatReaderDate(null)).toBe('')
  })
})
