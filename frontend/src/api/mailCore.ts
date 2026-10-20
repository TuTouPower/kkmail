import { mailCoreBaseUrl } from '../lib/mailCoreFlag'
import type { MailItem } from './queries'

export interface MailCoreMessage {
  id: string
  account_id: string
  subject: string
  from_address: string
  from_name: string | null
  sort_time: string
  is_read: boolean
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
  accountId?: string
  cursorSortTime?: string
  cursorMessageId?: string
  signal?: AbortSignal
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const base = mailCoreBaseUrl()
  const res = await fetch(`${base}${path}`, { headers: { Accept: 'application/json' }, signal })
  if (!res.ok) {
    throw new Error(`mail-core ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

export function fetchMailCoreInbox(opts: MailCoreInboxQuery | number = 40): Promise<MailCoreInboxPage> {
  const q = typeof opts === 'number' ? { limit: opts } : opts
  const params = new URLSearchParams()
  params.set('limit', String(q.limit ?? 40))
  if (q.accountId) params.set('account_id', q.accountId)
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
    has_attachments: m.has_attachments,
    body_preview: m.snippet || undefined,
    folder: 'inbox',
    accountEmail: m.account_id,
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

/** Subscribe to mail-core SSE. Returns an unsubscribe function. */
export function subscribeMailCoreEvents(
  onEvent: (event: string, data: unknown, id: string | null) => void,
  onError?: (err: Event) => void,
): () => void {
  const base = mailCoreBaseUrl()
  const es = new EventSource(`${base}/api/events`)
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
