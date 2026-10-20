/** Feature flag for the mail-core greenfield list/reader bridge.
 *
 * Enable when any of:
 * - `VITE_MAIL_CORE=1` (explicit build flag)
 * - `VITE_MAIL_CORE_DEFAULT=1` (cutover build: mail-core preferred)
 * - runtime `window.__KKMAIL_CONFIG__.mailCoreDefault === true`
 *   (Flask injects this when env `MAIL_CORE_DEFAULT=1` — no rebuild required)
 *
 * Explicit `VITE_MAIL_CORE=0` / `false` / `off` forces Flask-only.
 * Login and non-mail routes are unaffected.
 */

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
  if (explicit === 'on') return true
  const buildDefault = parseFlag(import.meta.env.VITE_MAIL_CORE_DEFAULT)
  if (buildDefault === 'on') return true
  if (runtimeConfig().mailCoreDefault) return true
  return false
}

/** Base URL for mail-core FastAPI. Empty = same-origin `/mail-core` proxy. */
export function mailCoreBaseUrl(): string {
  const runtime = runtimeConfig().mailCoreBase
  if (runtime && String(runtime).trim()) return String(runtime).replace(/\/$/, '')
  const raw = String(import.meta.env.VITE_MAIL_CORE_BASE || '').trim()
  if (raw) return raw.replace(/\/$/, '')
  return '/mail-core'
}
