import { useCallback, useEffect, useRef, useState } from 'react'
import { postJson, UNAUTHORIZED_EVENT } from '../api/client'
import { errorMessage } from '../lib/actions'
import { logDiagnostic } from '../lib/diagnostics'
import { viewToSyncScope } from '../lib/sync_scope'
import { useMailStore } from '../store/mailStore'

const AUTO_TRIGGER_COOLDOWN_MS = 12_000
const ACTIVITY_HEARTBEAT_MS = 20_000

interface SyncRequestResponse {
  id: string
  state: string
  errors?: Array<{ safe_message?: string | null }>
}

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
        // Unified client: CSRF token, token refresh, 401 handling, timeout
        // and ApiError parsing are shared with every other write.
        const data = await postJson<SyncRequestResponse>('/api/mail/sync/delta', {
          ...scope,
          trigger,
          client_request_id: clientRequestId,
        })

        activeRequestIdRef.current = data.id

        if (data.state === 'complete' || data.state === 'failed') {
          setIsSyncing(false)
          if (data.state === 'failed') {
            setLastError(data.errors?.[0]?.safe_message || '同步遇到异常')
          }
        }
      } catch (err: unknown) {
        setIsSyncing(false)
        setLastError(errorMessage(err, '同步请求失败'))
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

  // Periodic activity heartbeat: visible page + live session only. Failures
  // are background telemetry — they go to the sanitized diagnostics channel,
  // never to the user-facing error banner (which would repeat every 20s).
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return
    let loggedIn = true
    const onUnauthorized = () => { loggedIn = false }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    const interval = setInterval(() => {
      if (!loggedIn) return
      if (document.visibilityState !== 'visible') return
      const scope = viewToSyncScope(view)
      const accountIds = scope.account_id ? [scope.account_id] : []
      if (accountIds.length === 0) return
      void postJson('/api/mail/sync/activity', { account_ids: accountIds }).catch((err: unknown) => {
        logDiagnostic('warn', 'api', '活动心跳上报失败', {
          error: errorMessage(err, '未知错误'),
        })
      })
    }, ACTIVITY_HEARTBEAT_MS)
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
      clearInterval(interval)
    }
  }, [enabled, view])

  return {
    isSyncing,
    lastError,
    triggerManualSync,
  }
}
