/**
 * Waiting on manually triggered sync requests.
 *
 * The sync POST endpoints only queue work and return a SyncRequestOut whose
 * state is usually still queued/running. The immediate-sync buttons spin
 * until every request they started reaches a terminal state, so this helper
 * polls the request report endpoint — deliberately without a deadline: the
 * wait lasts as long as the sync itself lasts. Owners that go away (list
 * view unmounted mid-sync) cancel through `isCancelled`; the backend sync
 * keeps running regardless.
 */

import { api, type SyncRequestOut } from './client'

export const SYNC_POLL_INTERVAL_MS = 1_000

/**
 * How many poll rounds in a row may fail (transient 5xx, network blip)
 * before the wait gives up and reports failure. A failed poll says nothing
 * about the sync itself — the backend may still finish it successfully —
 * so a single error must not end the wait; only a sustained outage does.
 * Any successful round resets the budget.
 */
export const SYNC_POLL_MAX_CONSECUTIVE_FAILURES = 3

export const BACKGROUND_SYNC_POLL_MAX_ATTEMPTS = 120
export const BACKGROUND_SYNC_POLL_MAX_FAILURES = 5

export function isSyncTerminalState(state: SyncRequestOut['state']): boolean {
  return state === 'complete' || state === 'failed'
}

/**
 * Failure detail for the error channel: the first safe_message carried by a
 * failed request, a generic fallback when the backend gave none, or null
 * when nothing failed.
 */
export function syncFailureDetail(reports: readonly SyncRequestOut[]): string | null {
  for (const report of reports) {
    if (report.state !== 'failed') continue
    const message = (report.errors ?? []).map((error) => error.safe_message).find((text) => !!text)
    return message ?? '同步失败'
  }
  return null
}

/**
 * A21: Whether any of the completed immediate sync requests launched a
 * background sync for non-inbox folders that is still in flight.
 */
export function hasActiveBackgroundSync(reports: readonly SyncRequestOut[]): boolean {
  return reports.some(
    (report) =>
      Boolean(report.background_request_id) &&
      (report.background_state === 'queued' || report.background_state === 'running'),
  )
}

/**
 * A21: Failure detail specifically for decoupled background folder sync.
 */
export function backgroundSyncFailureDetail(reports: readonly SyncRequestOut[]): string | null {
  for (const report of reports) {
    if (report.background_state !== 'failed') continue
    const message = (report.background_errors ?? []).map((error) => error.safe_message).find((text) => !!text)
    return message ?? '部分文件夹同步失败'
  }
  return null
}

export interface BackgroundSyncProgress {
  active: boolean
  state: 'queued' | 'running' | 'complete' | 'failed' | null
  error: string | null
}

export interface PollBackgroundSyncOptions {
  onProgress?: (progress: BackgroundSyncProgress) => void
  isCancelled?: () => boolean
  pollIntervalMs?: number
  maxAttempts?: number
  maxFailures?: number
}

/**
 * A21: Monitor decoupled background folder discovery and sync independently
 * without holding the primary sync button in a spinning state.
 */
export async function pollBackgroundSync(
  initial: readonly SyncRequestOut[],
  callbacks: PollBackgroundSyncOptions = {},
): Promise<void> {
  const hasBg = initial.some((r) => Boolean(r.background_request_id))
  if (!hasBg) return

  const interval = callbacks.pollIntervalMs ?? SYNC_POLL_INTERVAL_MS
  const maxAttempts = callbacks.maxAttempts ?? BACKGROUND_SYNC_POLL_MAX_ATTEMPTS
  const maxFailures = callbacks.maxFailures ?? BACKGROUND_SYNC_POLL_MAX_FAILURES

  let activeReports = [...initial]
  let consecutiveFailures = 0
  let attempts = 0

  for (;;) {
    if (callbacks.isCancelled?.()) return

    const stillActive = activeReports.filter(
      (r) =>
        Boolean(r.background_request_id) &&
        r.background_state !== 'complete' &&
        r.background_state !== 'failed',
    )
    if (!stillActive.length) {
      const err = backgroundSyncFailureDetail(activeReports)
      callbacks.onProgress?.({
        active: false,
        state: err ? 'failed' : 'complete',
        error: err,
      })
      return
    }

    if (attempts >= maxAttempts) {
      callbacks.onProgress?.({
        active: false,
        state: 'failed',
        error: '后台同步超时',
      })
      return
    }

    callbacks.onProgress?.({
      active: true,
      state: 'running',
      error: null,
    })

    await new Promise<void>((resolve) => setTimeout(resolve, interval))
    if (callbacks.isCancelled?.()) return

    attempts += 1

    try {
      const freshBg = await Promise.all(
        stillActive.map((r) => api.getSyncRequest(r.background_request_id!)),
      )
      if (callbacks.isCancelled?.()) return
      consecutiveFailures = 0
      const freshById = new Map(freshBg.map((r) => [r.id, r]))
      activeReports = activeReports.map((r) => {
        if (!r.background_request_id) return r
        const fresh = freshById.get(r.background_request_id)
        if (!fresh) return r
        return {
          ...r,
          background_state: fresh.state,
          background_errors: fresh.errors,
        }
      })
    } catch (err) {
      if (callbacks.isCancelled?.()) return
      consecutiveFailures += 1
      if (consecutiveFailures >= maxFailures) {
        callbacks.onProgress?.({
          active: false,
          state: 'failed',
          error: err instanceof Error ? err.message : '后台同步网络请求连续失败',
        })
        return
      }
    }
  }
}

export interface SyncWaitResult {
  reports: SyncRequestOut[]
  cancelled: boolean
}

export async function waitForSyncRequests(
  initial: readonly SyncRequestOut[],
  options: { isCancelled?: () => boolean; pollIntervalMs?: number } = {},
): Promise<SyncWaitResult> {
  const interval = options.pollIntervalMs ?? SYNC_POLL_INTERVAL_MS
  let current = [...initial]
  let consecutivePollFailures = 0
  for (;;) {
    if (current.every((report) => isSyncTerminalState(report.state))) {
      return { reports: current, cancelled: false }
    }
    if (options.isCancelled?.()) return { reports: current, cancelled: true }
    const pending = current.filter((report) => !isSyncTerminalState(report.state))
    try {
      const fresh = await Promise.all(pending.map((report) => api.getSyncRequest(report.id)))
      consecutivePollFailures = 0
      const byId = new Map(fresh.map((report) => [report.id, report]))
      current = current.map((report) => byId.get(report.id) ?? report)
    } catch (error) {
      // Tolerated while the consecutive-failure budget lasts: keep the
      // last known reports and retry after the interval. The error only
      // surfaces once the budget is exhausted.
      consecutivePollFailures += 1
      if (consecutivePollFailures >= SYNC_POLL_MAX_CONSECUTIVE_FAILURES) throw error
    }
    if (current.every((report) => isSyncTerminalState(report.state))) {
      return { reports: current, cancelled: false }
    }
    if (options.isCancelled?.()) return { reports: current, cancelled: true }
    await new Promise<void>((resolve) => setTimeout(resolve, interval))
  }
}
