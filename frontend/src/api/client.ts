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
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }

  if (options.method && options.method !== 'GET' && options.method !== 'HEAD') {
    const token = await ensureCsrf()
    if (token) headers['X-CSRFToken'] = token
  }

  const res = await fetch(path, {
    credentials: 'include',
    headers,
    ...options,
  })

  if (res.status === 401 || res.redirected) {
    throw { status: 401, message: '未登录' } as ApiError
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

export const api = {
  async getCsrf() {
    return ensureCsrf()
  },

  async login(password: string, sessionDays = 30) {
    return request<{ success: boolean; message?: string; error?: string }>('/login', {
      method: 'POST',
      body: JSON.stringify({ password, session_duration_days: sessionDays }),
    })
  },

  async logout() {
    csrfToken = null
    window.location.href = '/logout'
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

  async getVersion() {
    return request<{ version_status?: unknown }>('/api/version-status')
  },
}

export default api
