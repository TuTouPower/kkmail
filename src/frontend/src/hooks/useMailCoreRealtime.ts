import { useEffect } from 'react'
import { subscribeMailCoreStream } from '../api/sseStream'
import { invalidateMailListQueries, invalidateMailStatsQueries, queryClient, queryKeys } from '../api/queries'
import { UNAUTHORIZED_EVENT } from '../api/client'

/** Events that mean cached message lists may be stale. */
export const MAIL_CORE_INBOX_INVALIDATE_EVENTS = new Set([
  'account.updated',
  'message.upserted',
  'message.removed',
  'folder.stats_updated',
  'remote_operation.updated',
  'client.resync_hint',
  'sync.completed',
])

const ARCHIVE_DETAIL_INVALIDATE_EVENTS = new Set([
  'archive.progress',
  'archive.completed',
  'archive.paused_quota',
])

export function shouldInvalidateMailCoreInbox(eventType: string): boolean {
  return MAIL_CORE_INBOX_INVALIDATE_EVENTS.has(eventType)
}

export function extractMessageIds(data: unknown): string[] {
  if (!data) return []
  if (typeof data === 'string') return [data]
  if (typeof data === 'object') {
    const obj = data as Record<string, unknown>
    const ids = new Set<string>()
    let primaryId: string | null = null
    if (typeof obj.message_id === 'string' && obj.message_id) primaryId = obj.message_id
    else if (typeof obj.id === 'string' && obj.id) primaryId = obj.id
    if (primaryId) ids.add(primaryId)
    if (Array.isArray(obj.message_ids)) {
      for (const id of obj.message_ids) {
        if (typeof id === 'string' && id) ids.add(id)
      }
    }
    return [...ids]
  }
  return []
}

function refreshMailCoreCaches() {
  void invalidateMailListQueries()
  void invalidateMailStatsQueries()
  void queryClient.invalidateQueries({ queryKey: ['detail', 'mail-core'] })
}

export const REALTIME_THROTTLE_MS = 150

export function createThrottledInvalidator(qc: typeof queryClient, delayMs = REALTIME_THROTTLE_MS) {
  let timer: ReturnType<typeof setTimeout> | null = null
  let invalidateMailLists = false
  let invalidateMailStats = false
  let invalidateAccounts = false
  let invalidateAllDetails = false
  const detailIdsToInvalidate = new Set<string>()

  function flush() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    if (invalidateAccounts) {
      invalidateAccounts = false
      invalidateMailLists = false
      invalidateMailStats = false
      void Promise.all([
        qc.invalidateQueries({ queryKey: queryKeys.accounts }),
        qc.invalidateQueries({ queryKey: queryKeys.groups }),
        qc.invalidateQueries({ queryKey: queryKeys.sidebarLayout }),
      ]).then(() => Promise.all([
        invalidateMailListQueries(qc),
        invalidateMailStatsQueries(qc),
      ]))
    } else {
      if (invalidateMailLists) {
        invalidateMailLists = false
        void invalidateMailListQueries(qc)
      }
      if (invalidateMailStats) {
        invalidateMailStats = false
        void invalidateMailStatsQueries(qc)
      }
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
    if (type === 'client.resync_hint') {
      invalidateAccounts = true
      invalidateMailLists = true
      invalidateMailStats = true
      invalidateAllDetails = true
      scheduled = true
    } else if (type === 'account.updated') {
      invalidateAccounts = true
      scheduled = true
    } else if (shouldInvalidateMailCoreInbox(type)) {
      invalidateMailLists = true
      if (type === 'folder.stats_updated' || type === 'sync.completed') {
        invalidateMailStats = true
      }
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
    if (ARCHIVE_DETAIL_INVALIDATE_EVENTS.has(type)) {
      const ids = extractMessageIds(data)
      for (const id of ids) detailIdsToInvalidate.add(id)
      scheduled = ids.length > 0 || scheduled
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
    invalidateMailLists = false
    invalidateMailStats = false
    invalidateAccounts = false
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

    let hasConnectedOnce = false
    let isReconnecting = false

    const throttler = createThrottledInvalidator(queryClient)

    const onOnline = () => {
      refreshMailCoreCaches()
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshMailCoreCaches()
      }
    }

    window.addEventListener('online', onOnline)
    document.addEventListener('visibilitychange', onVisibilityChange)

    const unsubscribe = subscribeMailCoreStream(
      (type, data) => {
        if (isReconnecting) {
          isReconnecting = false
          refreshMailCoreCaches()
        }
        throttler.handleEvent(type, data)
      },
      {
        onOpen: () => {
          if (hasConnectedOnce || isReconnecting) {
            refreshMailCoreCaches()
          }
          hasConnectedOnce = true
          isReconnecting = false
        },
        onError: () => {
          isReconnecting = true
        },
        onUnauthorized: (status) => {
          console.warn(`[SSE] Unauthorized stream access (${status}), stopping reconnect.`)
          window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
        },
        onVisibilityRecovery: () => {
          refreshMailCoreCaches()
        },
      },
    )

    return () => {
      window.removeEventListener('online', onOnline)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      unsubscribe()
      throttler.cancel()
    }
  }, [enabled])
}
