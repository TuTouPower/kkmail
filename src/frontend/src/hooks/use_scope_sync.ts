import { useCallback, useEffect, useRef, useState } from 'react'
import { apiBaseUrl } from '../lib/apiBase'
import { viewToSyncScope } from '../lib/sync_scope'
import { useMailStore } from '../store/mailStore'

const AUTO_TRIGGER_COOLDOWN_MS = 12_000
const ACTIVITY_HEARTBEAT_MS = 20_000

export function useScopeSync(enabled: boolean = true) {
  const view = useMailStore((s) => s.view)
  const [isSyncing, setIsSyncing] = useState(false)
  const [lastError, setLastError] = useState<string | null>(null)
  const lastAutoTriggerRef = useRef<number>(0)
  const activeRequestIdRef = useRef<string | null>(null)

  const executeDeltaSync = useCallback(
    async (trigger: 'manual' | 'focus' | 'navigation') => {
      if (!enabled) return
      const scope = viewToSyncScope(view)
      const clientRequestId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`

      setIsSyncing(true)
      setLastError(null)

      try {
        const res = await fetch(`${apiBaseUrl()}/api/mail/sync/delta`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({
            ...scope,
            trigger,
            client_request_id: clientRequestId,
          }),
        })

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `同步失败 (${res.status})`)
        }

        const data = await res.json()
        activeRequestIdRef.current = data.id

        if (data.state === 'complete' || data.state === 'failed') {
          setIsSyncing(false)
          if (data.state === 'failed') {
            setLastError(data.errors?.[0]?.safe_message || '同步遇到异常')
          }
        }
      } catch (err: unknown) {
        setIsSyncing(false)
        setLastError(err instanceof Error ? err.message : '同步请求失败')
      }
    },
    [enabled, view],
  )

  const triggerManualSync = useCallback(() => {
    void executeDeltaSync('manual')
  }, [executeDeltaSync])

  // Automatic triggers on navigation
  useEffect(() => {
    if (!enabled) return
    const now = Date.now()
    if (now - lastAutoTriggerRef.current >= AUTO_TRIGGER_COOLDOWN_MS) {
      lastAutoTriggerRef.current = now
      void executeDeltaSync('navigation')
    }
  }, [enabled, view, executeDeltaSync])

  // Automatic triggers on window focus / visibility change
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return

    function onFocusOrVisible() {
      if (document.visibilityState !== 'visible') return
      const now = Date.now()
      if (now - lastAutoTriggerRef.current >= AUTO_TRIGGER_COOLDOWN_MS) {
        lastAutoTriggerRef.current = now
        void executeDeltaSync('focus')
      }
    }

    window.addEventListener('focus', onFocusOrVisible)
    document.addEventListener('visibilitychange', onFocusOrVisible)
    return () => {
      window.removeEventListener('focus', onFocusOrVisible)
      document.removeEventListener('visibilitychange', onFocusOrVisible)
    }
  }, [enabled, executeDeltaSync])

  // Periodic activity heartbeat
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return
    const interval = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      const scope = viewToSyncScope(view)
      const accountIds = scope.account_id ? [scope.account_id] : []
      if (accountIds.length > 0) {
        void fetch(`${apiBaseUrl()}/api/mail/sync/activity`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ account_ids: accountIds }),
        }).catch(() => {})
      }
    }, ACTIVITY_HEARTBEAT_MS)
    return () => clearInterval(interval)
  }, [enabled, view])

  return {
    isSyncing,
    lastError,
    triggerManualSync,
  }
}
