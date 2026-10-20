import { mailCoreBaseUrl } from '../lib/mailCoreFlag'

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

async function getJson<T>(path: string): Promise<T> {
  const base = mailCoreBaseUrl()
  const res = await fetch(`${base}${path}`, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`mail-core ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

export function fetchMailCoreInbox(limit = 40): Promise<MailCoreInboxPage> {
  return getJson(`/api/mail/inbox?limit=${limit}`)
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
  // Named events from server
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
