/** Base URL of the mail-core API. Empty string = same origin (the default). */

export type KkmailRuntimeConfig = {
  apiBase?: string
}

declare global {
  interface Window {
    __KKMAIL_CONFIG__?: KkmailRuntimeConfig
  }
}

// Trust boundary (A377): window.__KKMAIL_CONFIG__ is a trusted operator
// surface — it is injected by the server-served page shell or the desktop
// host, never by page/mail content. Even so, the value is validated before
// use and fails closed to same-origin: only absolute http(s) URLs without
// embedded credentials are accepted, so a corrupted or injected override
// cannot silently point API traffic (and session cookies) at an arbitrary
// scheme or origin.
function validateApiBase(raw: string): string {
  if (!raw) return ''
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return ''
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return ''
  if (url.username || url.password) return ''
  if (!url.hostname) return ''
  return raw.replace(/\/+$/, '')
}

export function apiBaseUrl(): string {
  const runtime = typeof window === 'undefined' ? undefined : window.__KKMAIL_CONFIG__?.apiBase
  const runtimeValue = String(runtime ?? '').trim()
  // An explicitly set runtime override is authoritative: if it is invalid we
  // fail closed to same-origin instead of falling back to the build-time
  // value, so a bad override can never be masked by a stale env value.
  if (runtimeValue) return validateApiBase(runtimeValue)
  return validateApiBase(String(import.meta.env.VITE_API_BASE || '').trim())
}
