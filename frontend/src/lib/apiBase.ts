/** Base URL of the mail-core API. Empty string = same origin (the default). */

export type KkmailRuntimeConfig = {
  apiBase?: string
}

declare global {
  interface Window {
    __KKMAIL_CONFIG__?: KkmailRuntimeConfig
  }
}

export function apiBaseUrl(): string {
  const runtime = typeof window === 'undefined' ? undefined : window.__KKMAIL_CONFIG__?.apiBase
  const raw = String(runtime || import.meta.env.VITE_API_BASE || '').trim()
  return raw.replace(/\/+$/, '')
}
