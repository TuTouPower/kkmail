const MONTHS: Record<string, number> = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 }

/**
 * Parse the date strings the backend returns: ISO 8601 (Graph), RFC 2822, and
 * IMAP INTERNALDATE ("20-Oct-2026 20:54:54 +0800"). Returns epoch ms or NaN.
 */
export function parseMailDate(value?: string | null): number {
  if (!value) return NaN
  const imap = /^\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})\s*$/.exec(value)
  if (imap) {
    const [, d, mon, y, hh, mm, ss, sign, oh, om] = imap
    const month = MONTHS[mon.toLowerCase()]
    if (month === undefined) return NaN
    const offset = (Number(oh) * 60 + Number(om)) * (sign === '+' ? 1 : -1)
    return Date.UTC(Number(y), month, Number(d), Number(hh), Number(mm), Number(ss)) - offset * 60_000
  }
  return Date.parse(value)
}

/** Newest-first comparator; unparsable dates sort last. */
export function compareMailDates(a?: string | null, b?: string | null, newestFirst = true): number {
  const ta = parseMailDate(a)
  const tb = parseMailDate(b)
  const na = Number.isNaN(ta)
  const nb = Number.isNaN(tb)
  if (na || nb) return na === nb ? 0 : na ? 1 : -1
  return newestFirst ? tb - ta : ta - tb
}
