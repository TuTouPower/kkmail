/**
 * Typed API client for the existing Flask backend.
 * All React components should go through this layer so that
 * upstream API changes only require updates here.
 */

export interface ApiError {
  status: number
  message: string
  code?: string
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include', // session cookie
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!res.ok) {
    const text = await res.text()
    throw { status: res.status, message: text || res.statusText } as ApiError
  }

  return res.json() as Promise<T>
}

export const api = {
  // Placeholder methods — will be filled as we map existing endpoints
  async getAccounts() {
    // return request('/api/accounts')
    return Promise.resolve([])
  },
  async getMessages(params: { accountId?: string; folder?: string; page?: number }) {
    // return request(`/api/messages?...`)
    return Promise.resolve([])
  },
  async markRead(ids: number[], read: boolean) {
    // return request('/api/messages/mark', { method: 'POST', body: JSON.stringify({ ids, read }) })
    return Promise.resolve({ ok: true })
  },
}

export default api
