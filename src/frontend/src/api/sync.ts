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
