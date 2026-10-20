/**
 * Typed API client for mail-core (the sole backend).
 *
 * One transport: Cookie session + CSRF header on unsafe methods + timeout.
 * Unsafe requests are never sent without a CSRF token.
 */

import { apiBaseUrl } from '../lib/apiBase'
import type {
  AccountCreateIn,
  AccountSummary,
  AccountsResponse,
  GroupCreateIn,
  GroupOut,
  GroupsResponse,
  LoginOut,
  MeOut,
  PasswordChangeIn,
  SettingsOut,
  SyncAllResponse,
} from './schemaTypes'

export type {
  AccountSummary,
  AccountsResponse,
  GroupsResponse,
  SyncAllResponse,
} from './schemaTypes'

export interface ApiError {
  status: number
  message: string
  code?: string
  payload?: unknown
}

export const UNAUTHORIZED_EVENT = 'kkmail:unauthorized'
export const DEFAULT_TIMEOUT_MS = 30_000

let csrfToken: string | null = null

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token || null
}

/** Test hook. */
export function __resetCsrfForTests() {
  csrfToken = null
}

function handleUnauthorized(): ApiError {
  csrfToken = null
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  return { status: 401, code: 'unauthorized', message: '登录已过期，请重新登录' }
}

async function fetchCsrfToken(): Promise<string | null> {
  try {
    const res = await fetch(`${apiBaseUrl()}/api/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' } })
    if (!res.ok) return null
    const data = (await res.json()) as { csrf_token?: string }
    csrfToken = data.csrf_token || null
    return csrfToken
  } catch {
    return null
  }
}

export interface RequestOptions extends RequestInit {
  /** Abort after this many ms and throw ApiError{code:'timeout'}. */
  timeoutMs?: number
}

/** mail-core answers 403 {detail: {error, csrf_error: true}} on a stale/missing token. */
function isCsrfFailure(status: number, body: unknown): boolean {
  if (status !== 403 || !body || typeof body !== 'object') return false
  const detail = (body as { detail?: unknown }).detail
  return !!detail && typeof detail === 'object' && (detail as { csrf_error?: unknown }).csrf_error === true
}

/** Combine the caller's AbortSignal (e.g. from React Query) with a timeout. */
function withTimeout(signal: AbortSignal | null | undefined, timeoutMs: number) {
  const ctrl = new AbortController()
  let fired = false
  const timer = setTimeout(() => { fired = true; ctrl.abort() }, timeoutMs)
  const onAbort = () => ctrl.abort()
  if (signal) {
    if (signal.aborted) ctrl.abort()
    else signal.addEventListener('abort', onAbort, { once: true })
  }
  return {
    signal: ctrl.signal,
    timedOut: () => fired,
    done: () => { clearTimeout(timer); signal?.removeEventListener('abort', onAbort) },
  }
}

function errorFromBody(status: number, statusText: string, body: unknown): ApiError {
  let message = statusText || `HTTP ${status}`
  if (body && typeof body === 'object') {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') message = detail
    else if (detail && typeof detail === 'object' && !Array.isArray(detail) && typeof (detail as { error?: unknown }).error === 'string') {
      message = (detail as { error: string }).error
    } else if (Array.isArray(detail) && detail.length) {
      // FastAPI validation errors: [{loc, msg, type}]
      message = detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d))).join('; ')
    }
  }
  return { status, message, payload: body }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}, retriedCsrf = false): Promise<T> {
  const url = `${apiBaseUrl()}${path}`
  const { headers: extraHeaders, timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = options
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(rest.body != null ? { 'Content-Type': 'application/json' } : {}),
    ...(extraHeaders as Record<string, string> | undefined),
  }
  const method = (rest.method || 'GET').toUpperCase()
  const unsafe = method !== 'GET' && method !== 'HEAD'
  if (unsafe) {
    const token = csrfToken || (await fetchCsrfToken())
    if (!token) {
      // Never send a state-changing request without CSRF protection.
      throw { status: 0, code: 'csrf_unavailable', message: '无法获取 CSRF 令牌，请重新登录后重试' } as ApiError
    }
    headers['X-CSRF-Token'] = token
  }
  const tmo = withTimeout(callerSignal, timeoutMs)
  let res: Response
  try {
    res = await fetch(url, { ...rest, method, signal: tmo.signal, credentials: 'include', headers })
  } catch (err) {
    if (tmo.timedOut()) throw { status: 0, code: 'timeout', message: `请求超时（${Math.round(timeoutMs / 1000)} 秒）` } as ApiError
    throw err
  } finally {
    tmo.done()
  }
  if (res.status === 401) throw handleUnauthorized()
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch { /* non-JSON error body */ }
    if (unsafe && !retriedCsrf && isCsrfFailure(res.status, body)) {
      csrfToken = null
      return apiRequest<T>(path, options, true)
    }
    throw errorFromBody(res.status, res.statusText, body)
  }
  if (res.status === 204) return undefined as T
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) return res.json() as Promise<T>
  return (await res.text()) as unknown as T
}

export function postJson<T>(path: string, body: unknown = {}, opts: RequestOptions = {}): Promise<T> {
  return apiRequest<T>(path, { ...opts, method: 'POST', body: JSON.stringify(body) })
}


export const api = {
  /** true when the session cookie is valid (also caches the CSRF token). */
  async checkSession(): Promise<boolean> {
    try {
      const me = await apiRequest<MeOut>('/api/auth/me')
      setCsrfToken(me.csrf_token)
      return true
    } catch (err) {
      const e = err as ApiError
      if (e && e.status === 401) return false
      throw err
    }
  },

  async login(password: string): Promise<void> {
    // Login is CSRF-exempt on the server (no session yet); send directly.
    const res = await fetch(`${apiBaseUrl()}/api/auth/login`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    })
    let body: unknown = null
    try { body = await res.json() } catch { /* ignore */ }
    if (!res.ok) throw errorFromBody(res.status, res.statusText, body)
    setCsrfToken((body as LoginOut | null)?.csrf_token)
  },

  async logout(): Promise<void> {
    try {
      await postJson('/api/auth/logout')
    } catch { /* session may already be gone */ }
    csrfToken = null
    window.location.assign('/')
  },

  getGroups() {
    return apiRequest<GroupsResponse>('/api/groups')
  },

  getAccounts(params: { group_id?: string; limit?: number; offset?: number } = {}) {
    const q = new URLSearchParams()
    if (params.group_id) q.set('group_id', String(params.group_id))
    if (params.limit != null) q.set('limit', String(params.limit))
    if (params.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return apiRequest<AccountsResponse>(`/api/accounts${qs ? '?' + qs : ''}`)
  },

  addAccount(payload: AccountCreateIn) {
    return postJson<AccountSummary>('/api/accounts', payload)
  },

  deleteAccount(id: string) {
    return apiRequest<unknown>(`/api/accounts/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },

  syncAll() {
    return postJson<SyncAllResponse>('/api/accounts/sync-all')
  },

  syncAccount(id: string) {
    return postJson<unknown>(`/api/accounts/${encodeURIComponent(id)}/sync`)
  },

  createGroup(payload: GroupCreateIn) {
    return postJson<GroupOut>('/api/groups', payload)
  },

  deleteGroup(id: string) {
    return apiRequest<unknown>(`/api/groups/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },

  getSettings() {
    return apiRequest<SettingsOut>('/api/settings')
  },

  updateSettings(settings: Record<string, string>) {
    return apiRequest<SettingsOut>('/api/settings', { method: 'PUT', body: JSON.stringify({ settings }) })
  },

  changePassword(currentPassword: string, newPassword: string) {
    const body: PasswordChangeIn = {
      current_login_password: currentPassword,
      login_password: newPassword,
    }
    return postJson<unknown>('/api/auth/password', body)
  },
}

export default api
