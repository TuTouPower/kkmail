import { parseMailDate } from './mailDate'

const DAY_MS = 24 * 60 * 60 * 1000

/** Apple Mail–style list date: concrete time within 24h, otherwise a short date. */
export function formatListDate(value?: string | null, now = Date.now()): string {
  if (!value) return ''
  const ms = parseMailDate(value)
  if (!Number.isFinite(ms) || ms <= 0) return ''
  const d = new Date(ms)
  const age = now - ms
  if (age >= 0 && age < DAY_MS) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  // Same calendar year → weekday + M/D; otherwise include year.
  const sameYear = d.getFullYear() === new Date(now).getFullYear()
  if (sameYear) {
    const weekday = d.toLocaleDateString('zh-CN', { weekday: 'short' })
    const md = d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
    return `${weekday} ${md}`
  }
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' })
}

/** Short, localized date for the reader header. */
export function formatReaderDate(value?: string | null): string {
  if (!value) return ''
  const ms = parseMailDate(value)
  if (!Number.isFinite(ms) || ms <= 0) return value
  return new Date(ms).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}
