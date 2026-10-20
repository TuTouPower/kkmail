import { useEffect } from 'react'
import { subscribeMailCoreEvents } from '../api/mailCore'
import { queryClient } from '../api/queries'

/** Events that mean cached message lists may be stale. */
export const MAIL_CORE_INBOX_INVALIDATE_EVENTS = new Set([
  'message.upserted',
  'message.removed',
  'folder.stats_updated',
  'remote_operation.updated',
  'client.resync_hint',
  'sync.completed',
])

export function shouldInvalidateMailCoreInbox(eventType: string): boolean {
  return MAIL_CORE_INBOX_INVALIDATE_EVENTS.has(eventType)
}

/** While signed in, subscribe to mail-core SSE and refetch message lists on relevant events. */
export function useMailCoreRealtime(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return
    return subscribeMailCoreEvents(
      (type) => {
        if (shouldInvalidateMailCoreInbox(type)) void queryClient.invalidateQueries({ queryKey: ['mail-core'] })
      },
      () => {
        /* EventSource reconnects on its own */
      },
    )
  }, [enabled])
}
