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

export function extractMessageIds(data: unknown): string[] {
  if (!data) return []
  if (typeof data === 'string') return [data]
  if (typeof data === 'object') {
    const obj = data as Record<string, unknown>
    const ids: string[] = []
    if (typeof obj.message_id === 'string' && obj.message_id) ids.push(obj.message_id)
    if (typeof obj.id === 'string' && obj.id) ids.push(obj.id)
    if (Array.isArray(obj.message_ids)) {
      for (const id of obj.message_ids) {
        if (typeof id === 'string' && id) ids.push(id)
      }
    }
    return ids
  }
  return []
}

export const REALTIME_THROTTLE_MS = 150

export function createThrottledInvalidator(qc: typeof queryClient, delayMs = REALTIME_THROTTLE_MS) {
  let timer: ReturnType<typeof setTimeout> | null = null
  let invalidateMailCore = false
  let invalidateAllDetails = false
  const detailIdsToInvalidate = new Set<string>()

  function flush() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    if (invalidateMailCore) {
      invalidateMailCore = false
      void qc.invalidateQueries({ queryKey: ['mail-core'] })
    }
    if (invalidateAllDetails) {
      invalidateAllDetails = false
      detailIdsToInvalidate.clear()
      void qc.invalidateQueries({ queryKey: ['detail', 'mail-core'] })
    } else if (detailIdsToInvalidate.size > 0) {
      const ids = Array.from(detailIdsToInvalidate)
      detailIdsToInvalidate.clear()
      for (const id of ids) {
        void qc.invalidateQueries({ queryKey: ['detail', 'mail-core', id] })
      }
    }
  }

  function schedule() {
    if (timer === null) {
      timer = setTimeout(flush, delayMs)
    }
  }

  function handleEvent(type: string, data: unknown) {
    let scheduled = false
    if (shouldInvalidateMailCoreInbox(type)) {
      invalidateMailCore = true
      scheduled = true
    }
    if (type === 'message.upserted' || type === 'message.removed') {
      const ids = extractMessageIds(data)
      if (ids.length) {
        for (const id of ids) detailIdsToInvalidate.add(id)
      } else {
        invalidateAllDetails = true
      }
      scheduled = true
    }
    if (scheduled) {
      schedule()
    }
  }

  function cancel() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    detailIdsToInvalidate.clear()
    invalidateMailCore = false
    invalidateAllDetails = false
  }

  return {
    handleEvent,
    flush,
    cancel,
  }
}

/** While signed in, subscribe to mail-core SSE and refetch message lists on relevant events. */
export function useMailCoreRealtime(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return
    const throttler = createThrottledInvalidator(queryClient)
    const unsubscribe = subscribeMailCoreEvents(
      (type, data) => {
        throttler.handleEvent(type, data)
      },
      () => {
        /* EventSource reconnects on its own */
      },
    )
    return () => {
      unsubscribe()
      throttler.cancel()
    }
  }, [enabled])
}
