/**
 * Typed API client for mail-core (the sole backend).
 *
 * One transport: Cookie session + CSRF header on unsafe methods + timeout.
 * Unsafe requests are never sent without a CSRF token.
 */

import { apiBaseUrl } from '../lib/apiBase'
import type {
  AccountCreateIn,
  AccountUpdateIn,
  AccountSummary,
  AccountsResponse,
  GroupCreateIn,
  GroupOut,
  GroupsResponse,
  LoginOut,
  MeOut,
  OAuthActiveOut,
  OAuthCancelOut,
  OAuthFlowStatusOut,
  OAuthMetadataOut,
  OAuthStartIn,
  OAuthStartOut,
  PasswordChangeIn,
  SettingsOut,
  SidebarLayoutSnapshotOut,
  SyncAllResponse,
} from './schemaTypes'

export type {
  AccountSummary,
  AccountsResponse,
  GroupsResponse,
  OAuthFlowStatusOut,
  OAuthMetadataOut,
  OAuthStartIn,
  OAuthStartOut,
  SyncAllResponse,
} from './schemaTypes'

export interface ApiError {
  status: number
  message: string
  code?: string
  payload?: unknown
  retryAfterSeconds?: number
}

export const UNAUTHORIZED_EVENT = 'kkmail:unauthorized'
export const DEFAULT_TIMEOUT_MS = 30_000

let csrfToken: string | null = null
/** In-flight /api/auth/me so concurrent unsafe writes share one CSRF fetch (singleflight). */
let csrfInflight: Promise<string | null> | null = null

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token || null
}

/** Test hook. */
export function __resetCsrfForTests() {
  csrfToken = null
  csrfInflight = null
}

function handleUnauthorized(): ApiError {
  csrfToken = null
  csrfInflight = null
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  return { status: 401, code: 'unauthorized', message: '登录已过期，请重新登录' }
}

async function fetchCsrfToken(timeoutMs = DEFAULT_TIMEOUT_MS): Promise<string | null> {
  if (csrfToken) return csrfToken
  if (csrfInflight) return csrfInflight
  const tmo = withTimeout(undefined, timeoutMs)
  csrfInflight = (async () => {
    try {
      const res = await fetch(`${apiBaseUrl()}/api/auth/me`, {
        credentials: 'include',
        headers: { Accept: 'application/json' },
        signal: tmo.signal,
      })
      if (res.status === 401) throw handleUnauthorized()
      if (!res.ok) {
        let body: unknown = null
        try {
          body = await underTimeout(res.json(), tmo.signal, timeoutMs, tmo.timedOut)
        } catch (err) {
          if (tmo.timedOut()) throw err
          /* non-JSON or empty error body */
        }
        throw errorFromBody(res.status, res.statusText, body, res.headers.get('Retry-After'))
      }
      const data = (await underTimeout(res.json(), tmo.signal, timeoutMs, tmo.timedOut)) as { csrf_token?: string }
      csrfToken = data.csrf_token || null
      return csrfToken
    } catch (err) {
      if (tmo.timedOut()) {
        throw { status: 0, code: 'timeout', message: `请求超时（${Math.round(timeoutMs / 1000)} 秒）` } as ApiError
      }
      if (isApiError(err)) throw err
      if (err instanceof SyntaxError) {
        throw { status: 0, code: 'invalid_response', message: 'CSRF 令牌响应无效' } as ApiError
      }
      throw { status: 0, code: 'network_error', message: '网络请求失败，无法获取 CSRF 令牌' } as ApiError
    } finally {
      tmo.done()
      csrfInflight = null
    }
  })()
  return csrfInflight
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

function errorFromBody(status: number, statusText: string, body: unknown, retryAfterHeader?: string | null): ApiError {
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
  const retryAfter = retryAfterHeader?.trim()
  const retryAfterSeconds = retryAfter && /^\d+$/.test(retryAfter) ? Number(retryAfter) : undefined
  return { status, message, payload: body, ...(retryAfterSeconds ? { retryAfterSeconds } : {}) }
}

function isApiError(error: unknown): error is ApiError {
  return !!error && typeof error === 'object'
    && typeof (error as ApiError).status === 'number'
    && typeof (error as ApiError).message === 'string'
}


/** Reject when the shared timeout aborts, so hung body parses cannot outlive timeoutMs. */
function underTimeout<T>(work: Promise<T>, signal: AbortSignal, timeoutMs: number, timedOut: () => boolean): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const fail = () => {
      reject({ status: 0, code: 'timeout', message: `请求超时（${Math.round(timeoutMs / 1000)} 秒）` } as ApiError)
    }
    if (timedOut() || signal.aborted) {
      fail()
      return
    }
    const onAbort = () => fail()
    signal.addEventListener('abort', onAbort, { once: true })
    work.then(
      (v) => { signal.removeEventListener('abort', onAbort); resolve(v) },
      (e) => { signal.removeEventListener('abort', onAbort); reject(e) },
    )
  })
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
    const token = csrfToken || (await fetchCsrfToken(timeoutMs))
    if (!token) {
      // Never send a state-changing request without CSRF protection.
      throw { status: 0, code: 'csrf_unavailable', message: '无法获取 CSRF 令牌，请稍后重试' } as ApiError
    }
    headers['X-CSRF-Token'] = token
  }
  const tmo = withTimeout(callerSignal, timeoutMs)
  try {
    const res = await fetch(url, { ...rest, method, signal: tmo.signal, credentials: 'include', headers })
    if (res.status === 401) throw handleUnauthorized()
    if (!res.ok) {
      let body: unknown = null
      try {
        body = await underTimeout(res.json(), tmo.signal, timeoutMs, tmo.timedOut)
      } catch (err) {
        if (tmo.timedOut()) throw err
        /* non-JSON or empty error body */
      }
      if (unsafe && !retriedCsrf && isCsrfFailure(res.status, body)) {
        csrfToken = null
        tmo.done()
        return apiRequest<T>(path, options, true)
      }
      throw errorFromBody(res.status, res.statusText, body, res.headers.get('Retry-After'))
    }
    if (res.status === 204) return undefined as T
    const contentType = res.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      return await underTimeout(res.json() as Promise<T>, tmo.signal, timeoutMs, tmo.timedOut)
    }
    return await underTimeout(res.text() as Promise<unknown>, tmo.signal, timeoutMs, tmo.timedOut) as T
  } catch (err) {
    if (tmo.timedOut()) throw { status: 0, code: 'timeout', message: `请求超时（${Math.round(timeoutMs / 1000)} 秒）` } as ApiError
    throw err
  } finally {
    tmo.done()
  }
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

  async login(password: string, opts: { timeoutMs?: number } = {}): Promise<void> {
    // Login is CSRF-exempt on the server (no session yet); send directly.
    const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS
    const tmo = withTimeout(undefined, timeoutMs)
    try {
      const res = await fetch(`${apiBaseUrl()}/api/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
        signal: tmo.signal,
      })
      let body: unknown = null
      try {
        body = await underTimeout(res.json(), tmo.signal, timeoutMs, tmo.timedOut)
      } catch (err) {
        if (tmo.timedOut()) throw err
        /* ignore */
      }
      if (!res.ok) throw errorFromBody(res.status, res.statusText, body, res.headers.get('Retry-After'))
      setCsrfToken((body as LoginOut | null)?.csrf_token)
    } catch (err) {
      if (tmo.timedOut()) {
        throw { status: 0, code: 'timeout', message: `请求超时（${Math.round(timeoutMs / 1000)} 秒）` } as ApiError
      }
      throw err
    } finally {
      tmo.done()
    }
  },

  async logout(): Promise<void> {
    try {
      await postJson('/api/auth/logout')
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status
      if (status !== 401 && status !== 403) {
        throw err
      }
    }
    csrfToken = null
    csrfInflight = null
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

  updateAccount(id: string, payload: Partial<AccountUpdateIn>) {
    return apiRequest<AccountSummary>(`/api/accounts/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
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

  renameGroup(id: string, name: string) {
    return apiRequest<GroupOut>(`/api/groups/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ name }) })
  },

  getSidebarLayout() {
    return apiRequest<SidebarLayoutSnapshotOut>('/api/sidebar/layout')
  },

  deleteGroup(id: string) {
    return apiRequest<unknown>(`/api/groups/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },

  saveSidebarLayout(payload: {
    expected_revision: string
    group_ids: string[]
    master_account_ids: string[]
    ungrouped_account_ids: string[]
    group_account_ids: Record<string, string[]>
  }) {
    return apiRequest<unknown>('/api/sidebar/layout', { method: 'PUT', body: JSON.stringify(payload) })
  },

  resetSidebarAccountOrder(expectedRevision: string) {
    return apiRequest<unknown>('/api/sidebar/layout/default-order', {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    })
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

  getOAuthMetadata(provider = 'google') {
    const q = new URLSearchParams({ provider })
    return apiRequest<OAuthMetadataOut>(`/api/accounts/oauth/metadata?${q.toString()}`)
  },

  getActiveOAuthFlow() {
    return apiRequest<OAuthActiveOut>('/api/accounts/oauth/active')
  },

  startOAuthFlow(payload: OAuthStartIn) {
    return postJson<OAuthStartOut>('/api/accounts/oauth/start', payload)
  },

  getOAuthFlowStatus(flowId: string) {
    return apiRequest<OAuthFlowStatusOut>(`/api/accounts/oauth/flows/${encodeURIComponent(flowId)}`)
  },

  pollOAuthFlow(flowId: string) {
    return postJson<OAuthFlowStatusOut>(`/api/accounts/oauth/flows/${encodeURIComponent(flowId)}/poll`)
  },

  cancelOAuthFlow(flowId: string) {
    return postJson<OAuthCancelOut>(`/api/accounts/oauth/flows/${encodeURIComponent(flowId)}/cancel`)
  },
}

export default api
