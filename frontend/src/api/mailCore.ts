/** mail-core mail endpoints (inbox, search, detail, mutations, SSE). Shares the client transport. */

import { apiBaseUrl } from '../lib/apiBase'
import { apiRequest, postJson } from './client'
import type { MailDetail, MailItem } from './queries'

export interface MailCoreMessage {
  id: string
  account_id: string
  account_email: string | null
  subject: string
  from_address: string
  from_name: string | null
  sort_time: string
  is_read: boolean
  is_flagged: boolean
  has_attachments: boolean
  snippet: string | null
  folder_id: string | null
}

export interface MailCoreInboxPage {
  items: MailCoreMessage[]
  /** Opaque keyset token; pass back as `cursor`. */
  next_cursor: string | null
}

export interface MailCoreSearchPage {
  query: string
  items: MailCoreMessage[]
  total: number
  offset: number
  next_offset: number | null
}

export interface MailCoreInboxQuery {
  limit?: number
  /** mail-core account UUID */
  accountId?: string
  cursor?: string
  signal?: AbortSignal
}

export interface MutationResult {
  id: string
  account_id: string
  operation_id: string
  is_read?: boolean | null
  is_flagged?: boolean | null
  success: boolean
}

export function postMailCoreMessageRead(messageId: string, isRead: boolean, signal?: AbortSignal): Promise<MutationResult> {
  return postJson(`/api/mail/messages/${encodeURIComponent(messageId)}/read`, { is_read: isRead }, { signal })
}

export function postMailCoreMessageFlag(messageId: string, isFlagged: boolean, signal?: AbortSignal): Promise<MutationResult> {
  return postJson(`/api/mail/messages/${encodeURIComponent(messageId)}/flag`, { is_flagged: isFlagged }, { signal })
}

export function postMailCoreMessageTrash(messageId: string, signal?: AbortSignal): Promise<MutationResult> {
  return postJson(`/api/mail/messages/${encodeURIComponent(messageId)}/trash`, {}, { signal })
}

export function fetchMailCoreInbox(q: MailCoreInboxQuery = {}): Promise<MailCoreInboxPage> {
  const params = new URLSearchParams()
  params.set('limit', String(q.limit ?? 50))
  if (q.accountId) params.set('account_id', q.accountId)
  if (q.cursor) params.set('cursor', q.cursor)
  return apiRequest(`/api/mail/inbox?${params.toString()}`, { signal: q.signal })
}

export function fetchMailCoreSearch(
  query: string,
  opts: { accountId?: string; limit?: number; offset?: number; signal?: AbortSignal } = {},
): Promise<MailCoreSearchPage> {
  const params = new URLSearchParams({ q: query, limit: String(opts.limit ?? 50), offset: String(opts.offset ?? 0) })
  if (opts.accountId) params.set('account_id', opts.accountId)
  return apiRequest(`/api/mail/search?${params.toString()}`, { signal: opts.signal })
}

/** Map a mail-core list row into the SPA MailItem shape. */
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
    accountEmail: m.account_email || '',
    accountId: m.account_id,
  }
}

export interface MailCoreAttachment {
  id: string
  name: string
  contentType: string | null
  size: number | null
  is_inline: boolean
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
  is_flagged: boolean
  has_attachments: boolean
  snippet: string | null
  body: string
  body_type: 'html' | 'text' | 'empty'
  parse_error: string | null
  attachments: MailCoreAttachment[]
}

export function fetchMailCoreMessage(messageId: string, signal?: AbortSignal): Promise<MailCoreMessageDetail> {
  return apiRequest(`/api/mail/messages/${encodeURIComponent(messageId)}`, { signal })
}

export function mailCoreAttachmentUrl(attachmentId: string): string {
  return `${apiBaseUrl()}/api/mail/attachments/${encodeURIComponent(attachmentId)}`
}

/** Map mail-core detail into the reader's MailDetail shape. */
export function mailCoreToMailDetail(d: MailCoreMessageDetail): MailDetail {
  return {
    id: d.id,
    subject: d.subject,
    from: d.from,
    to: d.to,
    cc: d.cc || undefined,
    date: d.date,
    body: d.body,
    body_type: d.body_type === 'empty' ? undefined : d.body_type,
    has_attachments: d.has_attachments,
    attachments: d.attachments.map((a) => ({
      id: a.id,
      name: a.name,
      size: a.size ?? undefined,
      contentType: a.contentType ?? undefined,
    })),
  }
}

export const MAIL_CORE_EVENTS = [
  'message.upserted',
  'message.removed',
  'folder.stats_updated',
  'sync.progress',
  'sync.completed',
  'sync.error',
  'remote_operation.updated',
  'client.resync_hint',
] as const

/** Subscribe to mail-core SSE (cookie credentials; no API key in the URL). Returns unsubscribe. */
export function subscribeMailCoreEvents(
  onEvent: (event: string, data: unknown, id: string | null) => void,
  onError?: (err: Event) => void,
): () => void {
  const es = new EventSource(`${apiBaseUrl()}/api/events`, { withCredentials: true })
  const handler = (e: MessageEvent) => {
    let data: unknown = e.data
    try {
      data = JSON.parse(String(e.data))
    } catch {
      /* keep raw */
    }
    onEvent(e.type || 'message', data, e.lastEventId || null)
  }
  for (const name of MAIL_CORE_EVENTS) es.addEventListener(name, handler as EventListener)
  es.onmessage = handler
  es.onerror = (ev) => onError?.(ev)
  return () => es.close()
}
