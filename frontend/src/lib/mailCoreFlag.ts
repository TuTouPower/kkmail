/** Build-time feature flag for the mail-core greenfield bridge.
 *
 * Enable with `VITE_MAIL_CORE=1` (and optional `VITE_MAIL_CORE_BASE`).
 * When off, the Flask default SPA path is unchanged.
 */
export function isMailCoreEnabled(): boolean {
  const v = String(import.meta.env.VITE_MAIL_CORE || '').toLowerCase()
  return v === '1' || v === 'true' || v === 'yes'
}

/** Base URL for mail-core FastAPI. Empty = same-origin `/mail-core` proxy. */
export function mailCoreBaseUrl(): string {
  const raw = String(import.meta.env.VITE_MAIL_CORE_BASE || '').trim()
  if (raw) return raw.replace(/\/$/, '')
  return '/mail-core'
}
