/**
 * Typed API client — mail-core is the sole backend.
 * Session cookie + CSRF are handled here.
 */

import { mailCoreBaseUrl } from '../lib/mailCoreFlag'

export interface ApiError {
  status: number
  message: string
  code?: string
  payload?: unknown
}

let csrfToken: string | null = null

export const UNAUTHORIZED_EVENT = 'kkmail:unauthorized'

/** Session expired: drop the cached CSRF token and let the app show the login screen. */
function handleUnauthorized(): ApiError {
  csrfToken = null
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  return { status: 401, message: '登录已过期，请重新登录' }
}

async function fetchCsrfToken(): Promise<string | null> {
  try {
    const base = mailCoreBaseUrl() || ''
    const res = await fetch(`${base}/api/auth/me`, { credentials: 'include', headers: { Accept: 'application/json' } })
    if (!res.ok) return null
    const data = await res.json()
    csrfToken = data.csrf_token || null
    return csrfToken
  } catch {
    return null
  }
}

async function ensureCsrf(): Promise<string | null> {
  return csrfToken || fetchCsrfToken()
}

export interface RequestOptions extends RequestInit {
  /** Abort the request after this many ms and throw a timeout ApiError. */
  timeoutMs?: number
}

function isCsrfFailure(status: number, body: unknown): boolean {
  if (status !== 400 || !body || typeof body !== 'object') return false
  const b = body as { csrf_error?: unknown; error?: unknown }
  return b.csrf_error === true || (typeof b.error === 'string' && b.error.includes('CSRF'))
}

/** Combine the caller's AbortSignal (e.g. from React Query) with a timeout. */
function withTimeout(signal: AbortSignal | null | undefined, timeoutMs?: number) {
  if (!timeoutMs) return { signal: signal || undefined, timedOut: () => false, done: () => {} }
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


/** mail-core JSON helper (Cookie session + CSRF + timeout). */
async function mcRequest<T>(path: string, options: RequestOptions = {}, retriedCsrf = false): Promise<T> {
  const base = mailCoreBaseUrl() || ''
  const url = path.startsWith('http') ? path : `${base}${path}`
  const { headers: extraHeaders, timeoutMs = 30_000, signal: callerSignal, ...rest } = options
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(rest.body != null ? { 'Content-Type': 'application/json' } : {}),
    ...(extraHeaders as Record<string, string> | undefined),
  }
  const unsafe = !!options.method && options.method !== 'GET' && options.method !== 'HEAD'
  if (unsafe) {
    const token = csrfToken || (await ensureCsrf())
    if (token) {
      headers['X-CSRF-Token'] = token
      headers['X-CSRFToken'] = token
    }
  }
  const tmo = withTimeout(callerSignal, timeoutMs)
  let res: Response
  try {
    res = await fetch(url, { ...rest, signal: tmo.signal, credentials: 'include', headers })
  } catch (err) {
    if (tmo.timedOut()) throw { status: 0, code: 'timeout', message: `请求超时（${Math.round((timeoutMs || 0) / 1000)} 秒）` } as ApiError
    throw err
  } finally {
    tmo.done()
  }
  if (res.status === 401) throw handleUnauthorized()
  if (!res.ok) {
    let message = res.statusText
    let body: unknown = null
    try {
      body = await res.json()
      const b = body as { detail?: unknown; error?: string; message?: string }
      message = (typeof b.detail === 'string' ? b.detail : undefined) || b.error || b.message || message
    } catch { /* ignore */ }
    if (unsafe && !retriedCsrf && isCsrfFailure(res.status, body)) {
      csrfToken = null
      await fetchCsrfToken()
      return mcRequest<T>(path, options, true)
    }
    throw { status: res.status, message, payload: body } as ApiError
  }
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) return res.json() as Promise<T>
  return (await res.text()) as unknown as T
}

async function request<T>(path: string, options: RequestOptions = {}, _retriedCsrf = false): Promise<T> {
  // Sole backend is mail-core; keep name for older call sites / tests.
  return mcRequest<T>(path, options)
}

/** Test hook. */
export function __resetCsrfForTests() {
  csrfToken = null
}

export interface AccountSummary {
  id: string
  email: string
  group_id?: string
  group_name?: string
  group_color?: string
  status: string
  account_type: string
  provider: string
  authorization_type?: string
  forward_enabled?: boolean
  last_refresh_at?: string
  last_refresh_status?: string
  remark?: string
  tags?: unknown[]
  sync_status?: string
  display_name?: string | null
}

export interface AccountsResponse {
  success?: boolean
  accounts?: AccountSummary[]
  total?: number
  limit?: number
  offset?: number
  has_more?: boolean
  items?: AccountSummary[]
}

export interface EmailListItem {
  id?: string
  message_id?: string
  subject?: string
  from?: string
  sender?: string
  preview?: string
  received_at?: string
  date?: string
  is_read?: boolean
  unread?: boolean
  has_attachments?: boolean
  attachments?: number
  flagged?: boolean
}

export interface EmailListResponse {
  success?: boolean
  emails?: EmailListItem[]
  messages?: EmailListItem[]
  items?: EmailListItem[]
  total?: number
  error?: unknown
}

export interface RefreshEvent {
  type: string
  current?: number
  total?: number
  success_count?: number
  failed_count?: number
  message?: string
  email?: string
}

export function parseSseChunk(chunk: string): RefreshEvent[] {
  const events: RefreshEvent[] = []
  for (const line of chunk.split('\n')) {
    if (!line.startsWith('data:')) continue
    try {
      events.push(JSON.parse(line.slice(5).trim()) as RefreshEvent)
    } catch {
      /* ignore keep-alive or partial lines */
    }
  }
  return events
}

export const api = {
  async getCsrf() {
    return ensureCsrf()
  },

  /** true when the mail-core session cookie is valid. */
  async checkSession(): Promise<boolean> {
    try {
      const me = await mcRequest<{ authenticated?: boolean; csrf_token?: string }>('/api/auth/me')
      if (me.csrf_token) csrfToken = me.csrf_token
      return true
    } catch (err) {
      const e = err as ApiError
      if (e && e.status === 401) return false
      throw err
    }
  },

  async login(password: string, _sessionDays = 30) {
    const data = await mcRequest<{ ok?: boolean; csrf_token?: string; success?: boolean }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    })
    if (data.csrf_token) csrfToken = data.csrf_token
    return { success: true as boolean, message: 'ok' }
  },

  async logout() {
    try {
      await mcRequest('/api/auth/logout', { method: 'POST', body: '{}' })
    } catch { /* ignore */ }
    csrfToken = null
    window.location.assign('/')
  },

  async getGroups() {
    return request<{ groups?: unknown[]; items?: unknown[] }>('/api/groups')
  },

  async getAccounts(params: { group_id?: string; limit?: number; offset?: number } = {}) {
    const q = new URLSearchParams()
    if (params.group_id) q.set('group_id', String(params.group_id))
    if (params.limit != null) q.set('limit', String(params.limit))
    if (params.offset != null) q.set('offset', String(params.offset))
    const qs = q.toString()
    return mcRequest<AccountsResponse>(`/api/accounts${qs ? '?' + qs : ''}`)
  },

  async getEmails(email: string, params: { folder?: string; skip?: number; top?: number } = {}, opts: RequestOptions = {}) {
    const q = new URLSearchParams()
    q.set('folder', params.folder || 'inbox')
    q.set('skip', String(params.skip ?? 0))
    q.set('top', String(params.top ?? 30))
    return request<EmailListResponse>(`/api/emails/${encodeURIComponent(email)}?${q}`, opts)
  },

  async getEmailDetail(email: string, messageId: string, folder = 'inbox', idMode = '', opts: RequestOptions = {}) {
    const q = new URLSearchParams({ folder, method: idMode === 'imap' ? 'imap' : 'graph' })
    if (idMode) q.set('id_mode', idMode)
    return request<{ success?: boolean; email?: Record<string, unknown>; error?: unknown }>(
      `/api/email/${encodeURIComponent(email)}/${encodeURIComponent(messageId)}?${q}`,
      opts,
    )
  },

  async markRead(payload: { email: string; folder?: string; method?: string; items: Array<{ id: string; folder?: string; id_mode?: string }> }) {
    for (const item of payload.items || []) {
      await mcRequest(`/api/mail/messages/${encodeURIComponent(item.id)}/read`, {
        method: 'POST',
        body: JSON.stringify({ is_read: true }),
      })
    }
    return { success: true as boolean }
  },

  async deleteEmails(payload: { email: string; folder?: string; items: Array<{ id: string; folder?: string; id_mode?: string }> }) {
    // mail-core: trash each message by UUID (local-first + remote op).
    for (const item of payload.items || []) {
      await mcRequest(`/api/mail/messages/${encodeURIComponent(item.id)}/trash`, { method: 'POST', body: '{}' })
    }
    return { success: true as boolean }
  },

  async addAccountsMailCore(payload: {
    email: string
    provider: string
    display_name?: string
    group_id?: string
    credentials?: Record<string, unknown>
    config?: Record<string, unknown>
  }) {
    return mcRequest('/api/accounts', { method: 'POST', body: JSON.stringify(payload) })
  },

  async sendOutlookMail(_payload: Record<string, unknown>) {
    throw { status: 501, message: '发送未迁移到 mail-core' } as ApiError
  },

  async addAccounts(payload: {
    account_string: string
    group_id?: number
    account_format?: string
    provider?: string
    imap_host?: string
    imap_port?: number
    remark?: string
  }) {
    return request<{ success?: boolean; message?: string; error?: string; added_count?: number }>('/api/accounts', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async getTags() {
    return request<{ success?: boolean; tags?: Array<{ id: number; name: string; color?: string }> }>('/api/tags')
  },

  async getTempEmails() {
    return request<{ success?: boolean; emails?: Array<{ id: number; email?: string; address?: string; provider?: string }> }>('/api/temp-emails')
  },

  async getProjects() {
    return request<{ success?: boolean; data?: { projects?: Array<{ project_key?: string; name?: string; status?: string }> } }>('/api/projects')
  },

  async getOauthUrl() {
    return request<{ success?: boolean; auth_url?: string; client_id?: string; redirect_uri?: string }>('/api/oauth/auth-url')
  },

  async exchangeOauth(redirectedUrl: string) {
    return request<{ success?: boolean; error?: string; refresh_token?: string; client_id?: string }>('/api/oauth/exchange-token', {
      method: 'POST',
      body: JSON.stringify({ redirected_url: redirectedUrl }),
    })
  },

  async setForwarding(_ids: Array<string | number>, _enabled: boolean) {
    throw { status: 501, message: '转发未迁移到 mail-core' } as ApiError
  },

  async getTempEmailMessages(email: string) {
    return request<{ success?: boolean; messages?: Array<{ id?: string; subject?: string; from_address?: string }>; error?: string }>(
      `/api/temp-emails/${encodeURIComponent(email)}/messages`,
    )
  },

  async getForwardingLogs() {
    return request<{ success?: boolean; logs?: unknown[] }>('/api/accounts/forwarding-logs')
  },

  async generateTempEmail(payload: { provider?: string; prefix?: string; domain?: string } = {}) {
    return request<{ success?: boolean; email?: string; message?: string; error?: string }>('/api/temp-emails/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async deleteTempEmail(email: string) {
    return request(`/api/temp-emails/${encodeURIComponent(email)}`, { method: 'DELETE' })
  },

  async startProject(payload: { project_key: string; name?: string; description?: string }) {
    return request<{ success?: boolean; error?: string }>('/api/projects/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async testWebdav(config: { url: string; username?: string; password?: string }) {
    return request<{ success?: boolean; error?: string; message?: string }>('/api/settings/test-webdav-backup', {
      method: 'POST',
      body: JSON.stringify({ config }),
    })
  },

  async uploadWebdav(config: { url: string; username?: string; password?: string }) {
    return request<{ success?: boolean; error?: string; message?: string }>('/api/settings/upload-webdav-backup', {
      method: 'POST',
      body: JSON.stringify({ config }),
    })
  },

  async archiveProject(projectKey: string) {
    return request<{ success?: boolean; error?: string }>(`/api/projects/${encodeURIComponent(projectKey)}/archive`, { method: 'POST' })
  },

  async deleteProject(projectKey: string) {
    return request<{ success?: boolean; error?: string }>(`/api/projects/${encodeURIComponent(projectKey)}`, { method: 'DELETE' })
  },

  async getSettings() {
    return mcRequest<{ success?: boolean; settings?: Record<string, string> }>('/api/settings')
  },

  async updateSettings(payload: Record<string, string>) {
    if (payload.current_login_password && payload.login_password) {
      return mcRequest<{ success?: boolean; ok?: boolean }>('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({
          current_login_password: payload.current_login_password,
          login_password: payload.login_password,
        }),
      })
    }
    return mcRequest<{ success?: boolean; settings?: Record<string, string> }>('/api/settings', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async reauthorizeAccount(accountId: number, redirectedUrl: string) {
    return request<{ success?: boolean; error?: unknown }>(`/api/accounts/${accountId}/reauthorize`, {
      method: 'POST',
      body: JSON.stringify({ redirected_url: redirectedUrl }),
    })
  },

  async getSkins() {
    return request<{ success?: boolean; skins?: Array<{ id?: string; name?: string }>; active_skin_id?: string }>('/api/skins')
  },

  async createGroup(payload: { name: string; description?: string; color?: string }) {
    return mcRequest<{ success?: boolean; id?: string; name?: string }>('/api/groups', {
      method: 'POST',
      body: JSON.stringify({ name: payload.name, color: payload.color }),
    })
  },

  async deleteGroup(id: string | number) {
    return mcRequest<{ success?: boolean }>(`/api/groups/${encodeURIComponent(String(id))}`, { method: 'DELETE' })
  },

  async deleteAccount(id: string | number) {
    return mcRequest<{ success?: boolean }>(`/api/accounts/${encodeURIComponent(String(id))}`, { method: 'DELETE' })
  },

  async createTag(name: string) {
    return request<{ success?: boolean; error?: string }>('/api/tags', { method: 'POST', body: JSON.stringify({ name }) })
  },

  async deleteTag(id: number) {
    return request<{ success?: boolean; error?: string }>(`/api/tags/${id}`, { method: 'DELETE' })
  },

  /**
   * /api/accounts/refresh-all is a text/event-stream. Read it incrementally,
   * report each event, and resolve with the final complete/error event.
   */
  async refreshAllStream(onEvent?: (evt: RefreshEvent) => void): Promise<RefreshEvent> {
    const data = await mcRequest<{ success?: boolean; count?: number }>('/api/accounts/sync-all', { method: 'POST', body: '{}' })
    const evt: RefreshEvent = { type: 'done', message: `已排队 ${data.count ?? 0} 个同步任务`, success_count: data.count, total: data.count }
    onEvent?.(evt)
    return evt
  },

  async refreshAccount(id: string | number) {
    return mcRequest<{ success?: boolean }>(`/api/accounts/${encodeURIComponent(String(id))}/sync`, {
      method: 'POST',
      body: '{}',
    })
  },

  async getEmailShares() {
    return request<{ success?: boolean; shares?: Array<{ id: number; token?: string; email?: string; status?: string }> }>('/api/email-shares')
  },

  async createEmailShare(payload: { account_id: number; duration_minutes?: number; max_email_count?: number }) {
    return request<{ success?: boolean; error?: string; share?: { url?: string } }>('/api/email-shares', { method: 'POST', body: JSON.stringify(payload) })
  },

  async cancelEmailShare(id: number) {
    return request<{ success?: boolean; error?: string }>(`/api/email-shares/${id}/cancel`, { method: 'POST' })
  },

  async activateSkin(skinId: string) {
    return request<{ success?: boolean; error?: string }>(`/api/skins/${encodeURIComponent(skinId)}/activate`, { method: 'POST' })
  },

  attachmentUrl(email: string, messageId: string, attachmentId: string, folder = 'inbox', idMode = '') {
    const q = new URLSearchParams({ folder, method: idMode === 'imap' ? 'imap' : 'graph' })
    if (idMode) q.set('id_mode', idMode)
    return `/api/email/${encodeURIComponent(email)}/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}?${q}`
  },
}

export default api
