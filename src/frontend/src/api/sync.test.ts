import { afterEach, describe, expect, it, vi } from 'vitest'
import { __resetCsrfForTests, api, type SyncRequestOut } from './client'
import { isSyncTerminalState, SYNC_POLL_MAX_CONSECUTIVE_FAILURES, syncFailureDetail, waitForSyncRequests } from './sync'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function report(over: Partial<SyncRequestOut> = {}): SyncRequestOut {
  return {
    id: 'req-1',
    mode: 'delta',
    trigger: 'manual',
    state: 'queued',
    target_count: 1,
    queued_count: 1,
    running_count: 0,
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

describe('sync request api helpers', () => {
  it('syncAccount returns the typed sync request report', async () => {
    const mock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/auth/me') return json({ csrf_token: 'tok' })
      if (u === '/api/accounts/acc-1/sync') return json(report({ id: 'req-9', state: 'running' }), 202)
      return json({ detail: 'unexpected' }, 404)
    })
    vi.stubGlobal('fetch', mock)
    const result = await api.syncAccount('acc-1')
    expect(result.id).toBe('req-9')
    expect(result.state).toBe('running')
  })

  it('getSyncRequest reads the request report by id', async () => {
    const mock = vi.fn(async (url: string) => {
      const u = String(url)
      if (u === '/api/mail/sync/requests/req-9') return json(report({ id: 'req-9', state: 'complete' }))
      return json({ detail: 'unexpected' }, 404)
    })
    vi.stubGlobal('fetch', mock)
    const result = await api.getSyncRequest('req-9')
    expect(result.state).toBe('complete')
    expect(mock).toHaveBeenCalledTimes(1)
  })
})

describe('waitForSyncRequests', () => {
  it('resolves immediately when every request is already terminal, without polling', async () => {
    const mock = vi.fn(async () => json({ detail: 'unexpected' }, 404))
    vi.stubGlobal('fetch', mock)
    const { reports, cancelled } = await waitForSyncRequests([report({ state: 'complete' })], { pollIntervalMs: 1 })
    expect(cancelled).toBe(false)
    expect(reports[0].state).toBe('complete')
    expect(mock).not.toHaveBeenCalled()
  })

  it('polls non-terminal requests until they complete and does not refetch terminal ones', async () => {
    const polls = new Map<string, number>()
    const mock = vi.fn(async (url: string) => {
      const u = String(url)
      const id = u.split('/').pop()!
      const n = (polls.get(id) ?? 0) + 1
      polls.set(id, n)
      if (id === 'req-1') return json(report({ id, state: n >= 2 ? 'complete' : 'running' }))
      return json({ detail: 'unexpected' }, 404)
    })
    vi.stubGlobal('fetch', mock)
    const done = report({ id: 'req-2', state: 'complete' })
    const { reports, cancelled } = await waitForSyncRequests([report({ id: 'req-1', state: 'running' }), done], { pollIntervalMs: 1 })
    expect(cancelled).toBe(false)
    expect(reports.map((r) => r.state)).toEqual(['complete', 'complete'])
    expect(polls.get('req-1')).toBe(2)
    expect(polls.has('req-2')).toBe(false)
  })

  it('tolerates a transient poll failure and keeps waiting until completion', async () => {
    let polls = 0
    const mock = vi.fn(async () => {
      polls += 1
      if (polls === 1) throw new Error('network blip')
      return json(report({ state: 'complete' }))
    })
    vi.stubGlobal('fetch', mock)
    const { reports, cancelled } = await waitForSyncRequests([report({ state: 'running' })], { pollIntervalMs: 1 })
    expect(cancelled).toBe(false)
    expect(reports[0].state).toBe('complete')
    expect(polls).toBe(2)
  })

  it('resets the consecutive-failure budget after a successful poll round', async () => {
    // fail → running → fail → fail → complete: never three failures in a
    // row, so the wait must survive instead of giving up cumulatively.
    const script: Array<'fail' | 'running' | 'complete'> = ['fail', 'running', 'fail', 'fail', 'complete']
    let polls = 0
    const mock = vi.fn(async () => {
      const step = script[polls]
      polls += 1
      if (step === 'fail') throw new Error('network blip')
      return json(report({ state: step }))
    })
    vi.stubGlobal('fetch', mock)
    const { reports, cancelled } = await waitForSyncRequests([report({ state: 'running' })], { pollIntervalMs: 1 })
    expect(cancelled).toBe(false)
    expect(reports[0].state).toBe('complete')
    expect(polls).toBe(script.length)
  })

  it('gives up and rejects once consecutive poll failures reach the limit', async () => {
    const mock = vi.fn(async () => {
      throw new Error('network down')
    })
    vi.stubGlobal('fetch', mock)
    await expect(
      waitForSyncRequests([report({ state: 'running' })], { pollIntervalMs: 1 }),
    ).rejects.toThrow('network down')
    expect(mock).toHaveBeenCalledTimes(SYNC_POLL_MAX_CONSECUTIVE_FAILURES)
  })

  it('stops polling and reports cancellation when the owner goes away', async () => {
    const mock = vi.fn(async () => json(report({ state: 'running' })))
    vi.stubGlobal('fetch', mock)
    let cancelled = false
    const pending = waitForSyncRequests([report({ state: 'running' })], {
      pollIntervalMs: 1,
      isCancelled: () => cancelled,
    })
    cancelled = true
    const result = await pending
    expect(result.cancelled).toBe(true)
    expect(result.reports[0].state).toBe('running')
  })
})

describe('sync terminal state and failure detail', () => {
  it('treats only complete and failed as terminal', () => {
    expect(isSyncTerminalState('complete')).toBe(true)
    expect(isSyncTerminalState('failed')).toBe(true)
    expect(isSyncTerminalState('queued')).toBe(false)
    expect(isSyncTerminalState('running')).toBe(false)
  })

  it('returns null when nothing failed', () => {
    expect(syncFailureDetail([report({ state: 'complete' })])).toBeNull()
    expect(syncFailureDetail([])).toBeNull()
  })

  it('surfaces the first safe_message of a failed request', () => {
    const failed = report({ state: 'failed', errors: [{ target_id: 't1', code: 'auth', safe_message: '邮箱密码错误' }] })
    expect(syncFailureDetail([report({ state: 'complete' }), failed])).toBe('邮箱密码错误')
  })

  it('falls back to a generic message when a failed request has no safe_message', () => {
    expect(syncFailureDetail([report({ state: 'failed', errors: [] })])).toBe('同步失败')
  })
})
