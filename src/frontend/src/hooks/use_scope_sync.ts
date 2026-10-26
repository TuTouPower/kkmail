import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiRequest, postJson, UNAUTHORIZED_EVENT } from '../api/client'
import { errorMessage } from '../lib/actions'
import { logDiagnostic } from '../lib/diagnostics'
import { viewToSyncScope, type SyncScopePayload } from '../lib/sync_scope'
import { useMailStore } from '../store/mailStore'

const AUTO_TRIGGER_COOLDOWN_MS = 12_000
const ACTIVITY_HEARTBEAT_MS = 20_000

/** Poll cadence for the authoritative sync-request query (design §6). */
export const SYNC_REQUEST_POLL_MS = 2_000
/** Upper bound for the reload-recovery list query (design §6). */
export const SYNC_REQUEST_RECOVERY_LIMIT = 50

export type SyncRequestState = 'queued' | 'running' | 'complete' | 'failed'

export interface SyncRequestResponse {
  id: string
  state: SyncRequestState
  errors?: Array<{ code?: string; safe_message?: string | null }>
}

export function syncRequestQueryKey(requestId: string) {
  return ['sync-request', requestId] as const
}

export function syncRequestsQueryKey(scopeKey: string) {
  return ['sync-requests', scopeKey] as const
}

export function isTerminalSyncState(state: string | null | undefined): boolean {
  return state === 'complete' || state === 'failed'
}

export function isActiveSyncState(state: string | null | undefined): boolean {
  return state === 'queued' || state === 'running'
}

/** Stable identity for a sync scope; request IDs are remembered per key. */
export function syncScopeKey(scope: SyncScopePayload): string {
  return [
    scope.account_id || '',
    scope.group_id || '',
    scope.folder_id || '',
    scope.folder_role || '',
  ].join('|')
}

function syncRequestsListPath(scope: SyncScopePayload): string {
  const q = new URLSearchParams()
  q.set('limit', String(SYNC_REQUEST_RECOVERY_LIMIT))
  if (scope.account_id) q.set('account_id', scope.account_id)
  if (scope.group_id) q.set('group_id', scope.group_id)
  if (scope.folder_id) q.set('folder_id', scope.folder_id)
  if (scope.folder_role) q.set('folder_role', scope.folder_role)
  return `/api/mail/sync/requests?${q.toString()}`
}

/** The list endpoint may answer a bare array or a `{requests|items}` page. */
export function recentSyncRequests(data: unknown): SyncRequestResponse[] {
  const rows: unknown[] = Array.isArray(data)
    ? data
    : data && typeof data === 'object' && Array.isArray((data as { requests?: unknown }).requests)
      ? ((data as { requests: unknown[] }).requests)
      : data && typeof data === 'object' && Array.isArray((data as { items?: unknown }).items)
        ? ((data as { items: unknown[] }).items)
        : []
  return rows.filter(
    (row): row is SyncRequestResponse =>
      !!row && typeof row === 'object'
      && typeof (row as SyncRequestResponse).id === 'string'
      && typeof (row as SyncRequestResponse).state === 'string',
  )
}

function failedRequestMessage(request: SyncRequestResponse): string {
  const safe = request.errors?.[0]?.safe_message
  return safe ? errorMessage(safe, '同步遇到异常') : '同步遇到异常'
}

export function useScopeSync(enabled: boolean = true) {
  const view = useMailStore((s) => s.view)
  const queryClient = useQueryClient()
  const scope = useMemo(() => viewToSyncScope(view), [view])
  const scopeKey = useMemo(() => syncScopeKey(scope), [scope])

  // Request IDs live per scope (never a persisted running boolean): switching
  // away keeps the old request tracked under its own scope key, switching back
  // restores it. `isSyncing` below is derived from the current scope's
  // authoritative request state only.
  const [requestIdsByScope, setRequestIdsByScope] = useState<Record<string, string>>({})
  const [submitErrorsByScope, setSubmitErrorsByScope] = useState<Record<string, string>>({})
  const [pendingByScope, setPendingByScope] = useState<Record<string, boolean>>({})
  const [isVisible, setIsVisible] = useState<boolean>(
    () => typeof document === 'undefined' || document.visibilityState !== 'hidden',
  )
  const requestIdsRef = useRef<Record<string, string>>({})
  const pendingRef = useRef<Set<string>>(new Set())
  const lastAutoTriggerRef = useRef<Map<string, number>>(new Map())

  const rememberRequest = useCallback((forScopeKey: string, request: SyncRequestResponse) => {
    queryClient.setQueryData(syncRequestQueryKey(request.id), request)
    requestIdsRef.current = { ...requestIdsRef.current, [forScopeKey]: request.id }
    setRequestIdsByScope(requestIdsRef.current)
  }, [queryClient])

  // Reload / scope-entry recovery: ask the backend for this scope's recent
  // requests (max 50) and adopt the first unfinished one. A failure here is
  // silent — it only means there is nothing extra to recover.
  const recoveryQuery = useQuery({
    queryKey: syncRequestsQueryKey(scopeKey),
    queryFn: ({ signal }) => apiRequest<unknown>(syncRequestsListPath(scope), { signal }),
    enabled: enabled && !requestIdsByScope[scopeKey],
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  })
  const recoveredActive = useMemo(
    () => recentSyncRequests(recoveryQuery.data).find((r) => isActiveSyncState(r.state)) ?? null,
    [recoveryQuery.data],
  )

  useEffect(() => {
    if (!recoveredActive) return
    if (requestIdsRef.current[scopeKey]) return
    rememberRequest(scopeKey, recoveredActive)
  }, [recoveredActive, scopeKey, rememberRequest])

  const currentRequestId = requestIdsByScope[scopeKey] ?? null

  // Authoritative progress for the current scope's request. Polling starts as
  // soon as the POST (or recovery) yields an ID, runs at most every 2s while
  // the page is visible and the request is non-terminal, and stops at the
  // terminal state. SSE invalidation (useMailCoreRealtime) only ever targets
  // this exact ['sync-request', id] key.
  const requestQuery = useQuery({
    queryKey: syncRequestQueryKey(currentRequestId ?? '__none__'),
    queryFn: ({ signal }) =>
      apiRequest<SyncRequestResponse>(
        `/api/mail/sync/requests/${encodeURIComponent(currentRequestId!)}`,
        { signal },
      ),
    enabled: enabled && !!currentRequestId,
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      if (!isVisible) return false
      const data = query.state.data as SyncRequestResponse | undefined
      if (data && isTerminalSyncState(data.state)) return false
      return SYNC_REQUEST_POLL_MS
    },
  })
  const currentRequest = requestQuery.data ?? null

  // A polling network error means the progress is temporarily unavailable:
  // the last known non-terminal state stands, no success/failure is invented.
  const progressUnavailable =
    requestQuery.isError && !!currentRequest && isActiveSyncState(currentRequest.state)

  const isSyncing =
    !!pendingByScope[scopeKey]
    || (!!currentRequestId && !currentRequest)
    || (!!currentRequest && isActiveSyncState(currentRequest.state))
    || (!currentRequestId && !!recoveredActive)

  const lastError =
    submitErrorsByScope[scopeKey]
    ?? (currentRequest?.state === 'failed' ? failedRequestMessage(currentRequest) : null)

  const executeDeltaSync = useCallback(
    async (trigger: 'manual' | 'focus' | 'navigation') => {
      if (!enabled) return
      const requestScope = viewToSyncScope(view)
      const requestScopeKey = syncScopeKey(requestScope)

      // Same-scope in-flight requests block duplicate submission (manual or
      // automatic): the known request — submitted, still being submitted, or
      // recovered from the backend list — is the one already running.
      if (pendingRef.current.has(requestScopeKey)) return
      const knownId = requestIdsRef.current[requestScopeKey]
      if (knownId) {
        const known = queryClient.getQueryData<SyncRequestResponse>(syncRequestQueryKey(knownId))
        if (!known || isActiveSyncState(known.state)) return
      } else {
        const recent = recentSyncRequests(
          queryClient.getQueryData(syncRequestsQueryKey(requestScopeKey)),
        )
        const active = recent.find((r) => isActiveSyncState(r.state))
        if (active) {
          rememberRequest(requestScopeKey, active)
          return
        }
      }

      pendingRef.current.add(requestScopeKey)
      setPendingByScope((prev) => ({ ...prev, [requestScopeKey]: true }))
      setSubmitErrorsByScope((prev) => {
        if (!(requestScopeKey in prev)) return prev
        const next = { ...prev }
        delete next[requestScopeKey]
        return next
      })

      const clientRequestId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
      try {
        // Unified client: CSRF token, token refresh, 401 handling, timeout
        // and ApiError parsing are shared with every other write.
        const data = await postJson<SyncRequestResponse>('/api/mail/sync/delta', {
          ...requestScope,
          trigger,
          client_request_id: clientRequestId,
        })
        // Seed the authoritative query with the POST response; polling (or
        // the terminal state) takes it from here — isSyncing is derived.
        rememberRequest(requestScopeKey, data)
      } catch (err: unknown) {
        const message = errorMessage(err, '同步请求失败')
        setSubmitErrorsByScope((prev) => ({ ...prev, [requestScopeKey]: message }))
      } finally {
        pendingRef.current.delete(requestScopeKey)
        setPendingByScope((prev) => ({ ...prev, [requestScopeKey]: false }))
      }
    },
    [enabled, view, queryClient, rememberRequest],
  )

  const triggerManualSync = useCallback(() => {
    void executeDeltaSync('manual')
  }, [executeDeltaSync])

  // Automatic triggers on navigation — but first let the recovery query for
  // this scope settle: if the backend already has an unfinished request for
  // the scope, it is adopted above and no duplicate POST is sent.
  const recoveryBlocking =
    enabled && !currentRequestId && recoveryQuery.fetchStatus === 'fetching'
  useEffect(() => {
    if (!enabled || recoveryBlocking) return
    if (recoveredActive) return
    // F2: the cooldown is per scope. A single shared timestamp let a
    // sync for one folder swallow the navigation trigger of another
    // folder opened within 12s — and no later effect re-ran to fire it.
    const now = Date.now()
    if (now - (lastAutoTriggerRef.current.get(scopeKey) || 0) >= AUTO_TRIGGER_COOLDOWN_MS) {
      lastAutoTriggerRef.current.set(scopeKey, now)
      void executeDeltaSync('navigation')
    }
  }, [enabled, recoveryBlocking, recoveredActive, view, scopeKey, executeDeltaSync])

  // Page visibility: hidden pauses polling (via refetchInterval); becoming
  // visible reads the authoritative request state first.
  useEffect(() => {
    if (typeof document === 'undefined') return
    function onVisibilityChange() {
      const visible = document.visibilityState === 'visible'
      setIsVisible(visible)
      if (visible && currentRequestId) {
        void queryClient.invalidateQueries({
          queryKey: syncRequestQueryKey(currentRequestId),
          exact: true,
        })
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [currentRequestId, queryClient])

  // Automatic triggers on window focus / visibility change
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return

    function onFocusOrVisible() {
      if (document.visibilityState !== 'visible') return
      const now = Date.now()
      if (now - (lastAutoTriggerRef.current.get(scopeKey) || 0) >= AUTO_TRIGGER_COOLDOWN_MS) {
        lastAutoTriggerRef.current.set(scopeKey, now)
        void executeDeltaSync('focus')
      }
    }

    window.addEventListener('focus', onFocusOrVisible)
    document.addEventListener('visibilitychange', onFocusOrVisible)
    return () => {
      window.removeEventListener('focus', onFocusOrVisible)
      document.removeEventListener('visibilitychange', onFocusOrVisible)
    }
  }, [enabled, scopeKey, executeDeltaSync])

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
      const heartbeatScope = viewToSyncScope(view)
      const accountIds = heartbeatScope.account_id ? [heartbeatScope.account_id] : []
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
    progressUnavailable,
    currentRequestId,
    triggerManualSync,
  }
}
