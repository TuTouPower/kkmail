/** mail-core mail endpoints (inbox, search, detail, mutations, SSE). Shares the client transport. */

import { apiBaseUrl } from '../lib/apiBase'
import { apiRequest, postJson } from './client'
import type { MailDetail, MailItem } from './queries'
import type {
  GlobalStatsOut,
  MailCoreAttachment,
  MailCoreInboxPage,
  MailCoreMessage,
  MailCoreMessageDetail,
  MailCoreSearchPage,
  MutationResult,
} from './schemaTypes'

export type {
  AccountInboxStatsOut,
  GlobalStatsOut,
  MailCoreAttachment,
  MailCoreInboxPage,
  MailCoreMessage,
  MailCoreMessageDetail,
  MailCoreSearchPage,
  MutationResult,
} from './schemaTypes'

export interface MailCoreInboxQuery {
  limit?: number
  /** mail-core account UUID */
  accountId?: string
  cursor?: string
  is_read?: boolean
  is_flagged?: boolean
  folder_role?: string
  folder_id?: string
  sort_order?: 'asc' | 'desc'
  signal?: AbortSignal
}

export interface MarkAllReadParams {
  accountId?: string
  folder_role?: string
  folder_id?: string
  is_flagged?: boolean
  signal?: AbortSignal
}

export interface MarkAllReadResult {
  success: boolean
  count: number
  account_id?: string | null
}

export function postMailCoreMarkAllRead(
  params: MarkAllReadParams = {},
): Promise<MarkAllReadResult> {
  const body: Record<string, unknown> = {}
  if (params.folder_id) {
    body.folder_id = params.folder_id
  } else {
    body.folder_role = params.folder_role ?? 'inbox'
  }
  if (params.accountId) body.account_id = params.accountId
  if (params.is_flagged !== undefined) body.is_flagged = params.is_flagged
  return postJson('/api/mail/mark-all-read', body, { signal: params.signal })
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
  if (q.sort_order) params.set('sort_order', q.sort_order)
  if (q.accountId) params.set('account_id', q.accountId)
  if (q.cursor) params.set('cursor', q.cursor)
  if (q.is_read !== undefined) params.set('is_read', String(q.is_read))
  if (q.is_flagged !== undefined) params.set('is_flagged', String(q.is_flagged))
  if (q.folder_role) params.set('folder_role', q.folder_role)
  if (q.folder_id) params.set('folder_id', q.folder_id)
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
    // folder_id is the list identity; never invent 'inbox' (search may span roles).
    folder: m.folder_id || undefined,
    // email vs id must stay split — never fall back account_id into accountEmail.
    accountEmail: m.account_email ?? '',
    accountId: m.account_id,
  }
}

export function fetchGlobalStats(signal?: AbortSignal): Promise<GlobalStatsOut> {
  return apiRequest('/api/mail/stats', { signal })
}

export function fetchMailCoreMessage(messageId: string, signal?: AbortSignal): Promise<MailCoreMessageDetail> {
  return apiRequest(`/api/mail/messages/${encodeURIComponent(messageId)}`, { signal })
}

export function mailCoreAttachmentUrl(attachmentId: string): string {
  return `${apiBaseUrl()}/api/mail/attachments/${encodeURIComponent(attachmentId)}`
}

function detailBodyType(raw: string): MailDetail['body_type'] {
  return raw === 'html' || raw === 'text' ? raw : undefined
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
    body_type: detailBodyType(d.body_type),
    parse_error: d.parse_error ?? null,
    has_attachments: d.has_attachments,
    attachments: d.attachments.map((a: MailCoreAttachment) => ({
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
  onOpen?: () => void,
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
  // Named events only. Do not also set es.onmessage: pairing it with a 'message'
  // listener (or relying on both) historically double-dispatched the same SSE frame.
  // Backend always emits an explicit event: field (see mail_core/api/sse.py).
  for (const name of MAIL_CORE_EVENTS) es.addEventListener(name, handler as EventListener)
  if (onOpen) es.onopen = () => onOpen()
  es.onerror = (ev) => onError?.(ev)
  return () => es.close()
}
