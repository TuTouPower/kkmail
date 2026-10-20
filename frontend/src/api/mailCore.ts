import { isMailCoreEnabled, mailCoreBaseUrl } from '../lib/mailCoreFlag'
import type { MailItem } from './queries'

export interface MailCoreMessage {
  id: string
  account_id: string
  /** Mailbox email when API hydrates it (prefer over treating UUID as email). */
  account_email?: string | null
  subject: string
  from_address: string
  from_name: string | null
  sort_time: string
  is_read: boolean
  is_flagged?: boolean
  has_attachments: boolean
  snippet: string | null
  folder_id: string | null
}

export interface MailCoreInboxPage {
  items: MailCoreMessage[]
  next_cursor: { sort_time?: string; message_id?: string } | null
}

export interface MailCoreInboxQuery {
  limit?: number
  /** mail-core account UUID */
  accountId?: string
  /** Prefer this over Flask numeric ids when filtering one mailbox */
  accountEmail?: string
  cursorSortTime?: string
  cursorMessageId?: string
  signal?: AbortSignal
}

const DEFAULT_TIMEOUT_MS = 30_000

let mailCoreCsrf: string | null = null

export function getMailCoreCsrf(): string | null {
  return mailCoreCsrf
}

export function clearMailCoreAuth(): void {
  mailCoreCsrf = null
}

function withTimeout(signal: AbortSignal | undefined, timeoutMs: number) {
  const ctrl = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    ctrl.abort()
  }, timeoutMs)
  const onAbort = () => ctrl.abort()
  if (signal) {
    if (signal.aborted) ctrl.abort()
    else signal.addEventListener('abort', onAbort, { once: true })
  }
  return {
    signal: ctrl.signal,
    timedOut: () => timedOut,
    done: () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
    },
  }
}

async function mailCoreFetch(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<Response> {
  const base = mailCoreBaseUrl()
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, headers: extraHeaders, ...rest } = init
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(extraHeaders as Record<string, string> | undefined),
  }
  const method = (rest.method || 'GET').toUpperCase()
  const unsafe = method !== 'GET' && method !== 'HEAD'
  if (unsafe && mailCoreCsrf) {
    headers['X-CSRF-Token'] = mailCoreCsrf
  }
  const t = withTimeout(signal || undefined, timeoutMs)
  try {
    return await fetch(`${base}${path}`, {
      ...rest,
      signal: t.signal,
      credentials: 'include',
      headers,
    })
  } catch (err) {
    if (t.timedOut()) {
      throw new Error(`mail-core timeout after ${Math.round(timeoutMs / 1000)}s`)
    }
    throw err
  } finally {
    t.done()
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await mailCoreFetch(path, { signal })
  if (!res.ok) {
    throw new Error(`mail-core ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await mailCoreFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
    signal,
  })
  if (!res.ok) {
    throw new Error(`mail-core ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

/** Establish mail-core Cookie session (same password as product login). */
export async function mailCoreLogin(password: string, signal?: AbortSignal): Promise<{ csrf_token: string }> {
  const res = await mailCoreFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
    signal,
  })
  if (!res.ok) {
    throw new Error(`mail-core login ${res.status}: ${await res.text()}`)
  }
  const data = (await res.json()) as { csrf_token: string }
  mailCoreCsrf = data.csrf_token || null
  return data
}

export async function mailCoreLogout(signal?: AbortSignal): Promise<void> {
  try {
    await mailCoreFetch('/api/auth/logout', { method: 'POST', signal })
  } finally {
    clearMailCoreAuth()
  }
}

/** Refresh CSRF from /api/auth/me when a session cookie already exists. */
export async function mailCoreEnsureSession(signal?: AbortSignal): Promise<boolean> {
  try {
    const res = await mailCoreFetch('/api/auth/me', { signal })
    if (!res.ok) {
      clearMailCoreAuth()
      return false
    }
    const data = (await res.json()) as { csrf_token?: string }
    mailCoreCsrf = data.csrf_token || null
    return true
  } catch {
    clearMailCoreAuth()
    return false
  }
}

export function postMailCoreMessageRead(
  messageId: string,
  isRead = true,
  signal?: AbortSignal,
): Promise<{ id: string; is_read: boolean }> {
  return postJson(`/api/mail/messages/${encodeURIComponent(messageId)}/read`, { is_read: isRead }, signal)
}

export function postMailCoreMessageFlag(
  messageId: string,
  isFlagged = true,
  signal?: AbortSignal,
): Promise<{ id: string; is_flagged: boolean }> {
  return postJson(`/api/mail/messages/${encodeURIComponent(messageId)}/flag`, { is_flagged: isFlagged }, signal)
}

export function fetchMailCoreInbox(opts: MailCoreInboxQuery | number = 40): Promise<MailCoreInboxPage> {
  const q = typeof opts === 'number' ? { limit: opts } : opts
  const params = new URLSearchParams()
  params.set('limit', String(q.limit ?? 40))
  if (q.accountId) params.set('account_id', q.accountId)
  if (q.accountEmail) params.set('account_email', q.accountEmail)
  if (q.cursorSortTime) params.set('cursor_sort_time', q.cursorSortTime)
  if (q.cursorMessageId) params.set('cursor_message_id', q.cursorMessageId)
  return getJson(`/api/mail/inbox?${params.toString()}`, q.signal)
}

/** Map mail-core inbox rows into the SPA MailItem shape (Flask list UI). */
export function mailCoreToMailItem(m: MailCoreMessage): MailItem {
  const from = m.from_name ? `${m.from_name} <${m.from_address}>` : m.from_address
  return {
    id: m.id,
    subject: m.subject,
    from,
    date: m.sort_time,
    is_read: m.is_read,
    is_flagged: m.is_flagged,
    has_attachments: m.has_attachments,
    body_preview: m.snippet || undefined,
    folder: 'inbox',
    // Never treat UUID account_id as an email address.
    accountEmail: m.account_email || '',
    accountId: undefined,
    id_mode: 'mail_core',
  }
}

export interface MailCoreAttachment {
  id: string
  name: string
  contentType?: string | null
  size?: number | null
  is_inline?: boolean
}

export interface MailCoreMessageDetail {
  id: string
  account_id: string
  subject: string
  from_address: string
  from_name: string | null
  from: string
  to: string
  cc: string
  date: string
  is_read: boolean
  has_attachments: boolean
  snippet: string | null
  body: string
  body_type: string
  parse_error: string | null
  attachments: MailCoreAttachment[]
}

export function fetchMailCoreMessage(messageId: string, signal?: AbortSignal): Promise<MailCoreMessageDetail> {
  return getJson(`/api/mail/messages/${encodeURIComponent(messageId)}`, signal)
}

export function fetchMailCoreMessageBody(
  messageId: string,
  signal?: AbortSignal,
): Promise<{ id: string; body: string; body_type: string; parse_error: string | null; snippet: string | null }> {
  return getJson(`/api/mail/messages/${encodeURIComponent(messageId)}/body`, signal)
}

export function mailCoreAttachmentUrl(attachmentId: string): string {
  return `${mailCoreBaseUrl()}/api/mail/attachments/${encodeURIComponent(attachmentId)}`
}

/** Map mail-core detail into Flask MailDetail shape for MessageReader. */
export function mailCoreToMailDetail(d: MailCoreMessageDetail): import('./queries').MailDetail {
  return {
    id: d.id,
    subject: d.subject,
    from: d.from,
    to: d.to,
    cc: d.cc || undefined,
    date: d.date,
    body: d.body,
    body_type: d.body_type === 'html' ? 'html' : d.body_type === 'text' ? 'text' : undefined,
    has_attachments: d.has_attachments,
    attachments: (d.attachments || []).map((a) => ({
      id: a.id,
      name: a.name,
      size: a.size ?? undefined,
      contentType: a.contentType ?? undefined,
    })),
  }
}

export function fetchMailCoreHealth(): Promise<{ status: string; service?: string }> {
  return getJson('/health')
}

/** Subscribe to mail-core SSE. Returns an unsubscribe function. Cookie credentials only (no API key in query). */
export function subscribeMailCoreEvents(
  onEvent: (event: string, data: unknown, id: string | null) => void,
  onError?: (err: Event) => void,
): () => void {
  const base = mailCoreBaseUrl()
  const es = new EventSource(`${base}/api/events`, { withCredentials: true })
  const handler = (e: MessageEvent) => {
    let data: unknown = e.data
    try {
      data = JSON.parse(String(e.data))
    } catch {
      /* keep raw */
    }
    onEvent(e.type || 'message', data, e.lastEventId || null)
  }
  for (const name of [
    'message.upserted',
    'message.removed',
    'folder.stats_updated',
    'mail.changed',
    'folder.stats.changed',
    'sync.progress',
    'sync.completed',
    'client.resync_hint',
    'message',
  ]) {
    es.addEventListener(name, handler as EventListener)
  }
  es.onmessage = handler
  es.onerror = (ev) => onError?.(ev)
  return () => es.close()
}

export { isMailCoreEnabled }
