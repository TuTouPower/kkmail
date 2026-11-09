import { afterEach, describe, expect, it, vi } from 'vitest'
import { waitForSyncRequests } from '../api/sync'
import { __resetCsrfForTests, type SyncRequestOut } from '../api/client'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function report(over: Partial<SyncRequestOut> = {}): SyncRequestOut {
  return {
    id: 'req-1',
    mode: 'delta',
    trigger: 'manual',
    state: 'running',
    target_count: 1,
    queued_count: 0,
    running_count: 1,
    completed_count: 0,
    failed_count: 0,
    created_at: '2026-10-28T00:00:00Z',
    finished_at: null,
    errors: [],
    ...over,
  } as SyncRequestOut
}

afterEach(() => {
  vi.unstubAllGlobals()
  __resetCsrfForTests()
})

describe('waitForSyncRequests generation cancellation', () => {
  it('reports cancelled when the generation is retired while a poll resolves terminal', async () => {
    let releasePoll!: () => void
    const pollGate = new Promise<void>((resolve) => { releasePoll = resolve })
    let signalStarted!: () => void
    const started = new Promise<void>((resolve) => { signalStarted = resolve })
    vi.stubGlobal('fetch', vi.fn(async () => {
      signalStarted()
      await pollGate
      return json(report({ state: 'complete', running_count: 0, completed_count: 1 }))
    }))

    let active = true
    const pending = waitForSyncRequests([report()], {
      pollIntervalMs: 1,
      isCancelled: () => !active,
    })
    await started
    active = false
    releasePoll()
    const result = await pending
    expect(result.cancelled).toBe(true)
  })
})
