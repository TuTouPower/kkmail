/**
 * Typed API client for the existing Flask backend.
 * All React components go through this layer.
 * Session cookie + CSRF are handled here.
 */

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

async function ensureCsrf(): Promise<string | null> {
  if (csrfToken) return csrfToken
  try {
    const res = await fetch('/api/csrf-token', { credentials: 'include' })
    if (!res.ok) return null
    const data = await res.json()
    csrfToken = data.csrf_token || null
    return csrfToken
  } catch {
    return null
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { headers: extraHeaders, ...rest } = options
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(rest.body != null ? { 'Content-Type': 'application/json' } : {}),
    ...(extraHeaders as Record<string, string> | undefined),
  }

  if (options.method && options.method !== 'GET' && options.method !== 'HEAD') {
    const token = await ensureCsrf()
    if (token) headers['X-CSRFToken'] = token
  }

  // Spread caller options first so the merged headers (with CSRF) always win.
  const res = await fetch(path, {
    ...rest,
    credentials: 'include',
    headers,
  })

  if (res.status === 401 || res.redirected) {
    throw handleUnauthorized()
  }

  if (!res.ok) {
    let message = res.statusText
    try {
      const body = await res.json()
      message = body.error?.message || body.error || body.message || message
    } catch {
      /* ignore */
    }
    throw { status: res.status, message } as ApiError
  }

  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return res.json() as Promise<T>
  }
  return (await res.text()) as unknown as T
}

export interface AccountSummary {
  id: number
  email: string
  group_id?: number
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
}

export interface AccountsResponse {
  success?: boolean
  accounts?: AccountSummary[]
  total?: number
  limit?: number
  offset?: number
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

  /** true when the Flask session is valid. /api/csrf-token is login_required. */
  async checkSession(): Promise<boolean> {
    const res = await fetch('/api/csrf-token', { credentials: 'include', headers: { Accept: 'application/json' } })
    if (res.status === 401 || res.redirected) return false
    if (!res.ok) throw { status: res.status, message: res.statusText } as ApiError
    const data = await res.json().catch(() => ({}))
    csrfToken = data.csrf_token || null
    return true
  },

  async login(password: string, sessionDays = 30) {
    csrfToken = null
    return request<{ success: boolean; message?: string; error?: string }>('/login', {
      method: 'POST',
      body: JSON.stringify({ password, session_duration_days: sessionDays }),
    })
  },

  logout() {
    csrfToken = null
    window.location.assign('/logout')
  },

  async getGroups() {
    return request<{ groups?: unknown[]; items?: unknown[] }>('/api/groups')
  },

  async getAccounts(params: { group_id?: number; limit?: number; offset?: number } = {}) {
    const q = new URLSearchParams()
    if (params.group_id != null) q.set('group_id', String(params.group_id))
    if (params.limit) q.set('limit', String(params.limit))
    if (params.offset) q.set('offset', String(params.offset))
    const qs = q.toString()
    return request<AccountsResponse>(`/api/accounts${qs ? '?' + qs : ''}`)
  },

  async getEmails(email: string, params: { folder?: string; skip?: number; top?: number } = {}) {
    const q = new URLSearchParams()
    q.set('folder', params.folder || 'inbox')
    q.set('skip', String(params.skip ?? 0))
    q.set('top', String(params.top ?? 30))
    return request<EmailListResponse>(`/api/emails/${encodeURIComponent(email)}?${q}`)
  },

  async getEmailDetail(email: string, messageId: string, folder = 'inbox', idMode = '') {
    const q = new URLSearchParams({ folder, method: idMode === 'imap' ? 'imap' : 'graph' })
    if (idMode) q.set('id_mode', idMode)
    return request<{ success?: boolean; email?: Record<string, unknown>; error?: unknown }>(
      `/api/email/${encodeURIComponent(email)}/${encodeURIComponent(messageId)}?${q}`,
    )
  },

  async markRead(payload: { email: string; folder?: string; method?: string; items: Array<{ id: string; folder?: string; id_mode?: string }> }) {
    return request<{ success?: boolean; error?: unknown }>('/api/emails/mark-read', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async deleteEmails(payload: { email: string; folder?: string; items: Array<{ id: string; folder?: string; id_mode?: string }> }) {
    return request('/api/emails/delete', { method: 'POST', body: JSON.stringify(payload) })
  },

  async sendOutlookMail(payload: { account_id: number; recipients: string; subject: string; body: string }) {
    return request('/api/outlook/send-mail', { method: 'POST', body: JSON.stringify(payload) })
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

  async setForwarding(accountIds: number[], forwardEnabled: boolean) {
    return request<{ success?: boolean; message?: string; error?: string }>('/api/accounts/batch-update-forwarding', {
      method: 'POST',
      body: JSON.stringify({ account_ids: accountIds, forward_enabled: forwardEnabled }),
    })
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
    return request<{ success?: boolean; settings?: Record<string, string> }>('/api/settings')
  },

  async updateSettings(payload: Record<string, string>) {
    return request<{ success?: boolean; message?: string; error?: string }>('/api/settings', {
      method: 'PUT',
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
    return request<{ success?: boolean; error?: string }>('/api/groups', { method: 'POST', body: JSON.stringify(payload) })
  },

  async deleteGroup(id: number) {
    return request<{ success?: boolean; error?: string }>(`/api/groups/${id}`, { method: 'DELETE' })
  },

  async deleteAccount(id: number) {
    return request<{ success?: boolean; error?: string }>(`/api/accounts/${id}`, { method: 'DELETE' })
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
    const res = await fetch('/api/accounts/refresh-all', { credentials: 'include', headers: { Accept: 'text/event-stream' } })
    if (res.status === 401 || res.redirected) throw handleUnauthorized()
    if (!res.ok || !res.body) throw { status: res.status, message: res.statusText || '刷新失败' } as ApiError
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let last: RefreshEvent = { type: 'complete' }
    for (;;) {
      const { done, value } = await reader.read()
      if (value) buffer += decoder.decode(value, { stream: !done })
      const parts = buffer.split('\n\n')
      buffer = done ? '' : parts.pop() || ''
      for (const part of done ? parts.filter(Boolean) : parts) {
        for (const evt of parseSseChunk(part)) {
          last = evt
          onEvent?.(evt)
        }
      }
      if (done) break
    }
    return last
  },

  async refreshAccount(id: number) {
    return request<{ success?: boolean; error?: string }>(`/api/accounts/${id}/refresh`, { method: 'POST' })
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
