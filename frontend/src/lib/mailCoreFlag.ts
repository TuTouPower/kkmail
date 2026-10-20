/** mail-core is the sole backend. Flag kept for tests / optional off switch. */

export type KkmailRuntimeConfig = {
  mailCoreDefault?: boolean
  mailCoreBase?: string
}

declare global {
  interface Window {
    __KKMAIL_CONFIG__?: KkmailRuntimeConfig
  }
}

function runtimeConfig(): KkmailRuntimeConfig {
  if (typeof window === 'undefined') return {}
  return window.__KKMAIL_CONFIG__ || {}
}

function parseFlag(raw: unknown): 'on' | 'off' | 'unset' {
  const v = String(raw ?? '').toLowerCase().trim()
  if (!v) return 'unset'
  if (v === '0' || v === 'false' || v === 'no' || v === 'off') return 'off'
  if (v === '1' || v === 'true' || v === 'yes' || v === 'on') return 'on'
  return 'unset'
}

export function isMailCoreEnabled(): boolean {
  const explicit = parseFlag(import.meta.env.VITE_MAIL_CORE)
  if (explicit === 'off') return false
  return true
}

/** Base URL for mail-core FastAPI. Empty = same-origin. */
export function mailCoreBaseUrl(): string {
  const runtime = runtimeConfig().mailCoreBase
  if (runtime && String(runtime).trim()) return String(runtime).replace(/\/$/, '')
  const raw = String(import.meta.env.VITE_MAIL_CORE_BASE || '').trim()
  if (raw) return raw.replace(/\/$/, '')
  return ''
}
