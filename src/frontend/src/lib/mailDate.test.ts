import { describe, expect, it } from 'vitest'
import { compareMailDates, parseMailDate } from './mailDate'

describe('mail dates', () => {
  it('parses IMAP internaldate with offset', () => {
    expect(parseMailDate('20-Oct-2026 20:54:54 +0800')).toBe(Date.UTC(2026, 9, 20, 12, 54, 54))
  })
  it('sorts chronologically across months, not lexically', () => {
    const list = ['20-Oct-2026 10:00:00 +0800', '01-Nov-2026 10:00:00 +0800', '2026-10-25T00:00:00Z', 'garbage']
    expect([...list].sort((a, b) => compareMailDates(a, b))).toEqual([
      '01-Nov-2026 10:00:00 +0800', '2026-10-25T00:00:00Z', '20-Oct-2026 10:00:00 +0800', 'garbage',
    ])
  })
  it('keeps unknown dates last in either sort direction', () => {
    const values = [null, '2026-10-20T00:00:00Z', '2026-10-21T00:00:00Z']
    expect([...values].sort((a, b) => compareMailDates(a, b, true))).toEqual([
      '2026-10-21T00:00:00Z', '2026-10-20T00:00:00Z', null,
    ])
    expect([...values].sort((a, b) => compareMailDates(a, b, false))).toEqual([
      '2026-10-20T00:00:00Z', '2026-10-21T00:00:00Z', null,
    ])
  })
})
