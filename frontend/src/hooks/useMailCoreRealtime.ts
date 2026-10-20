import { useEffect } from 'react'
import { subscribeMailCoreEvents } from '../api/mailCore'
import { queryClient } from '../api/queries'
import { isMailCoreEnabled } from '../lib/mailCoreFlag'

/** Events that mean inbox / folder list may be stale. */
export const MAIL_CORE_INBOX_INVALIDATE_EVENTS = new Set([
  'message.upserted',
  'message.removed',
  'folder.stats_updated',
  'mail.changed',
  'folder.stats.changed',
  'client.resync_hint',
  'sync.completed',
])

export function shouldInvalidateMailCoreInbox(eventType: string): boolean {
  return MAIL_CORE_INBOX_INVALIDATE_EVENTS.has(eventType)
}

/**
 * When VITE_MAIL_CORE (or runtime flag) is on, subscribe to mail-core SSE and
 * invalidate/refetch the mail-core inbox query on message / folder-stats events.
 */
export function useMailCoreRealtime(): void {
  useEffect(() => {
    if (!isMailCoreEnabled()) return
    const stop = subscribeMailCoreEvents(
      (type) => {
        if (!shouldInvalidateMailCoreInbox(type)) return
        void queryClient.invalidateQueries({ queryKey: ['mail-core', 'inbox'] })
      },
      () => {
        /* disconnect; EventSource reconnects; no action */
      },
    )
    return stop
  }, [])
}
